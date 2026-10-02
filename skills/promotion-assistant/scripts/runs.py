"""Freeze reviewed recipients and checkpoint uncertainty before any provider effect."""
from collections import Counter
from contextlib import contextmanager
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
import uuid

from . import bandit, compliance, dispatch, events, email_contract, learning, private_storage, throttle

STATUSES = {'pending', 'complete', 'simulated', 'blocked', 'deferred', 'manual-prep', 'failed', 'uncertain'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def safe_id(value):
    if (not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', value)
            or value.endswith('.') or value.split('.')[0].upper() in {
                'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}):
        raise ValueError('run_id must be a safe directory component')
    return value


def aggregate(record):
    counts = dict(Counter(item['status'] for item in record['items']))
    status = ('blocked' if not counts else next(iter(counts)) if len(counts) == 1 else
              'uncertain' if 'uncertain' in counts else 'partial')
    return {**record, 'status': status, 'counts': counts}


def intent(record):
    return digest({'campaign': record['campaign'], 'scope': record['scope'],
                   'items': [{'idempotency_key': item['idempotency_key'], 'payload': item['payload']}
                             for item in record['items']]})


def save(cfg, record):
    path = cfg.data_path('metrics', 'runs', safe_id(record['run_id'])+'.json')
    record.update(aggregate(record))
    fd, name = tempfile.mkstemp(prefix='.'+path.name, dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(record, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        cfg.data_path('metrics', 'runs', path.name)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def lock(cfg, run_id):
    path = cfg.data_path('metrics', 'runs', run_id+'.lock')
    with path.open('x', encoding='utf-8') as stream:
        stream.write('run active; inspect stale lock before removal\n')
    try:
        yield
    finally:
        path.unlink()


def frozen_scope(cfg, arm):
    channel = arm.get('channel')
    registration = cfg.channel(channel)
    if not registration:
        raise ValueError('selected arm has no registered channel')
    registration = {key: value for key, value in registration.items() if key != 'live_authorize_token'}
    return {'product': cfg.product, 'channel': channel, 'registration': registration,
            'platform': registration.get('platform', channel),
            'account': registration.get('account_handle', 'default'),
            'action': arm.get('action', 'post'), 'arm': arm}


def expand(cfg, scope, run_id):
    arm, channel = scope['arm'], scope['registration']
    mode = channel.get('audience_mode')
    if not mode and (scope['platform'] == 'email' or channel.get('transport') in {'smtp', 'email'}):
        mode = 'addressed'
    base = {'channel': scope['channel'], 'platform': scope['platform'], 'account': scope['account'],
            'transport': channel.get('transport', 'post'), 'audience_mode': mode,
            'subject': arm.get('hook'), 'body': arm.get('body', ''),
            'cta': cfg.aff_base+(arm.get('utm', {}).get('content') or arm.get('id', '')),
            'utm': arm.get('utm', {}), 'from_addr': cfg.product.get('from_addr'),
            'physical_address': (cfg.product.get('compliance', {}) or {}).get('physical_address'),
            'unsubscribe': (cfg.product.get('compliance', {}) or {}).get('unsubscribe_url'),
            'email_helper_contract': channel.get('email_helper_contract')}
    errors, duplicates = [], 0
    if mode == 'owned_broadcast':
        destination = channel.get('destination')
        rows = [{'destination': destination}]
        if not isinstance(destination, str) or not destination.strip():
            errors.append('owned broadcast requires an explicit destination')
    elif mode == 'addressed':
        audiences = cfg.audiences()
        segments = audiences.get('segments') if isinstance(audiences, dict) else None
        rows = segments.get(arm.get('segment')) if isinstance(segments, dict) else None
        if not isinstance(rows, list) or not rows:
            rows = [{}]
            errors.append('missing, empty or malformed audience segment')
    else:
        rows = [{}]
        errors.append('channel must declare addressed or owned_broadcast audience mode')
    unique = {}
    for index, row in enumerate(rows):
        reasons = list(errors)
        if not isinstance(row, dict):
            row = {}
            reasons.append('malformed audience record')
        row = copy.deepcopy(row)
        if mode == 'addressed':
            raw_recipient = row.get('recipient')
            suppression_key = compliance.normalize_recipient(raw_recipient)
            recipient = raw_recipient if isinstance(raw_recipient, str) else ''
            if (scope['platform'] == 'email' or channel.get('transport') in {'smtp', 'email'}) and not compliance._looks_like_email(raw_recipient):
                recipient = ''
                reasons.append('missing or malformed email recipient')
            country = row.get('recipient_country')
            if isinstance(country, str):
                country = country.strip().upper()
            row.update(recipient=recipient, recipient_country=country)
            payload = {**base, 'recipient': recipient, 'destination': recipient,
                       'recipient_country': country, 'audience_metadata': row, 'suppression_key': suppression_key}
            if not recipient:
                # Retain rejected input separately from the deliverable address.
                payload['supplied_recipient'] = raw_recipient
            identity = suppression_key if recipient else 'invalid:'+str(index)
        else:
            payload = {**base, 'destination': row.get('destination')}
            identity = row.get('destination') if isinstance(row.get('destination'), str) and row['destination'] else 'invalid:'+str(index)
        if scope['platform'] == 'email' or channel.get('transport') in {'smtp', 'email'}:
            payload = email_contract.freeze(payload)
        if identity in unique:
            duplicates += 1
            def comparable(value):
                value = copy.deepcopy(value)
                value.pop('idempotency_key', None)
                if mode == 'addressed':
                    value.update(recipient=identity, destination=identity)
                    value['audience_metadata']['recipient'] = identity
                return value
            if comparable(unique[identity]['payload']) != comparable(payload):
                unique[identity]['review_reasons'].append('conflicting duplicate audience metadata')
            continue
        key = digest([run_id, scope, identity])
        payload['idempotency_key'] = key
        unique[identity] = {'idempotency_key': key, 'payload': payload, 'status': 'pending',
                            'receipt': None, 'reasons': reasons, 'review_reasons': reasons,
                            'safe_to_retry': True}
    return list(unique.values()), duplicates


def validate(record, cfg, campaign, channel):
    if (not isinstance(record, dict) or type(record.get('schema_version')) is not int
            or record['schema_version'] != 1 or record.get('campaign') != campaign
            or not isinstance(record.get('items'), list) or not record['items']
            or not isinstance(record.get('scope'), dict) or not isinstance(record.get('pick'), dict)):
        raise ValueError('invalid or incompatible saved run; inspect retained record')
    scope = record['scope']
    if channel is not None and channel != scope.get('channel'):
        raise ValueError('requested channel differs from frozen run')
    if not isinstance(scope.get('arm'), dict):
        raise ValueError('saved scope has no arm')
    arms = [arm for arm in cfg.copy(campaign) if arm.get('id') == scope['arm'].get('id')]
    if len(arms) != 1 or frozen_scope(cfg, arms[0]) != scope:
        raise ValueError('current product/channel/account/action/payload scope differs from frozen run')
    keys = []
    for item in record['items']:
        if (not isinstance(item, dict) or item.get('status') not in STATUSES
                or not isinstance(item.get('payload'), dict) or not isinstance(item.get('idempotency_key'), str)
                or not item['idempotency_key'] or item['payload'].get('idempotency_key') != item['idempotency_key']
                or type(item.get('safe_to_retry')) is not bool or 'receipt' not in item):
            raise ValueError('malformed saved item; unresolved work must be inspected')
        keys.append(item['idempotency_key'])
    if len(set(keys)) != len(keys) or record.get('intent_sha256') != intent(record):
        raise ValueError('saved run intent changed or has duplicate item identities')


def execute(cfg, campaign, *, env=None, clock=None, rng=None, conversion_window_s=None,
            channel=None, run_id=None, resume=False):
    clock = time.time if clock is None else clock
    record = None
    try:
        if resume and run_id is None:
            raise ValueError('resume requires an explicit run_id')
        run_id = safe_id(run_id) if run_id is not None else 'run-'+uuid.uuid4().hex
        cfg.metrics_dir()
        directory = cfg.data_path('metrics', 'runs')
        directory.mkdir(exist_ok=True)
        path = cfg.data_path('metrics', 'runs', run_id+'.json')
        with lock(cfg, run_id):
            band = bandit.Bandit(cfg.data_path('metrics', 'bandit-state.json'), rng=rng)
            thr = throttle.Throttle(cfg.data_path('metrics', 'throttle-state.json'), clock=clock, rng=rng)
            if resume:
                record = json.loads(private_storage.read_text(path))
                validate(record, cfg, campaign, channel)
                if record.get('run_id') != run_id:
                    raise ValueError('saved run ID mismatch')
            else:
                if path.exists():
                    raise ValueError('run already exists; explicit resume required')
                arms = cfg.copy(campaign)
                arms = [arm for arm in arms if isinstance(arm, dict) and arm.get('id')
                        and (channel is None or arm.get('channel') == channel)]
                if not arms:
                    return {'run_id': run_id, 'status': 'blocked', 'counts': {}, 'items': [],
                            'reason': 'no arms in requested campaign/channel scope'}
                if len({arm['id'] for arm in arms}) != len(arms):
                    raise ValueError('copy library contains duplicate arm identities')
                pick = band.select([arm['id'] for arm in arms])
                arm = next(arm for arm in arms if arm['id'] == pick['arm_id'])
                scope = copy.deepcopy(frozen_scope(cfg, arm))
                items, duplicates = expand(cfg, scope, run_id)
                record = {'schema_version': 1, 'run_id': run_id, 'campaign': campaign,
                          'scope': scope, 'pick': pick, 'items': items, 'duplicate_count': duplicates}
                record['intent_sha256'] = intent(record)
                with path.open('x', encoding='utf-8') as stream:
                    json.dump(aggregate(record), stream)
                    stream.flush()
                    os.fsync(stream.fileno())
            for item in record['items']:
                payload = item['payload']
                ok, reasons, eligibility, _ = dispatch.review(payload, cfg=cfg, channel=record['scope']['channel'])
                item['eligibility'] = eligibility
                identity = {**item, 'platform': record['scope']['platform'], 'account': record['scope']['account']}
                if item['status'] == 'simulated':
                    continue
                if item['status'] == 'complete':
                    if not dispatch.matching_receipt(item['receipt'], identity):
                        raise ValueError('completed item lacks a valid matching receipt')
                    continue
                if item['status'] == 'uncertain':
                    try:
                        proof = dispatch.reconcile_action(identity, cfg=cfg, env=env)
                    except Exception as exc:
                        proof = {'status': 'unknown', 'reason': type(exc).__name__}
                    if dispatch.matching_receipt(proof, identity):
                        item.update(status='complete', receipt=proof, reasons=[], safe_to_retry=False)
                        save(cfg, record)
                        continue
                    if not dispatch.matching_receipt(proof, identity, 'not_applied'):
                        item['reasons'] = reasons + ['provider outcome remains uncertain; no resend authorized']
                        continue
                    item.update(status='failed', receipt=proof, safe_to_retry=True)
                if item['status'] == 'failed' and not dispatch.matching_receipt(item['receipt'], identity, 'not_applied'):
                    item['safe_to_retry'] = False
                    continue

                def before_effect():
                    item.update(status='uncertain', safe_to_retry=False,
                                reasons=['provider effect started; outcome not yet confirmed'])
                    save(cfg, record)

                decision = {key: record['scope'][key] for key in ('channel', 'platform', 'account', 'action')}
                decision.update(record['pick'], payload=payload, audience_segment=record['scope']['arm'].get('segment'),
                    decision_id=item['idempotency_key'], idempotency_key=item['idempotency_key'],
                    review_reasons=item.get('review_reasons', []), _before_effect=before_effect)
                result = dispatch.dispatch(decision, cfg=cfg, throttle=thr, env=env)
                status = {'sent': 'complete', 'rejected': 'blocked', 'throttled': 'deferred'}.get(result['status'], result['status'])
                item.update(status=status, receipt=result.get('receipt'),
                            reasons=result.get('reasons') or ([result['reason']] if result.get('reason') else []),
                            safe_to_retry=result.get('safe_to_retry', False), eligibility=result['eligibility'])
                save(cfg, record)
            save(cfg, record)
            evs = events.read(cfg.data_path('metrics', 'events.jsonl'))
            reward, reward_status = learning.credit_observations(
                cfg.data_path('metrics', 'bandit-state.json'), evs, arm_id=record['pick']['arm_id'],
                decision_ids=[item['idempotency_key'] for item in record['items']],
                conversion_window_s=conversion_window_s, now=clock())
            result = aggregate(record)
            result = {key: result[key] for key in ('run_id', 'status', 'counts', 'items', 'duplicate_count')}
            result.update(arm=record['pick']['arm_id'], reward=reward, reward_status=reward_status)
            result['dispatch'] = {'status': result['items'][0]['status']} if len(result['items']) == 1 else {'status': result['status']}
            return result
    except Exception as exc:
        # The last durable intent remains authoritative if checkpointing or a later step fails.
        items = record.get('items', []) if isinstance(record, dict) else []
        if not isinstance(items, list) or not all(isinstance(item, dict) and isinstance(item.get('status'), str)
                                                and item['status'] in STATUSES for item in items):
            items = []
        result = aggregate({'run_id': run_id, 'items': items})
        result.update(reason=str(exc), status='uncertain' if any(item['status'] == 'uncertain' for item in items) else 'failed')
        return result
