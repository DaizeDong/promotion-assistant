#!/usr/bin/env python3
"""L3 dispatch — the ONE outbound exit. Fail-closed dry-run is the default, not an option.

Every real send/post/DM in the whole system goes through dispatch(). It asserts BOTH:
  1. product.json.send_mode == "live", AND
  2. environment token PROMO_LIVE_AUTHORIZED_<CHANNEL> is PRESENT (any non-empty value).
     Second factor strength is config-driven: if the per-channel config declares an expected
     `live_authorize_token`, the env value must additionally EQUAL it (constant-time compare);
     when no expected token is configured, the second factor is existence-only (any non-empty
     value authorizes). This is honest about the default — the existence-only fallback is
     intentional (the env token alone is the operator's per-channel arming gesture), and a
     configured secret upgrades it to a true match.
If either factor fails -> the action is SIMULATED: it still runs the full pipeline
(compliance gate -> throttle -> [would call provider] -> writes an event_type='simulated' row +
a dry-run.jsonl record with the would-send content and estimated recipients), but performs ZERO
network egress. This lets the metrics stream + bandit train with no real outreach.

Pipeline order (all dry-run too):  compliance.check  ->  throttle.reserve  ->  provider(live?)  ->
  events.append. A compliance/throttle rejection short-circuits and is logged (not a crash).
"""
from __future__ import annotations

import hmac
import json
import os
from pathlib import Path

from . import compliance, events, providers, email_contract, private_storage


def _authorized(channel: str, send_mode: str, *, env=None, expected=None) -> tuple:
    """Two-factor live gate. Factor 1: send_mode=="live". Factor 2: env token present, and
    (iff `expected` is configured) the env token must EQUAL it via constant-time compare.
    Fail-closed: any failure returns (False, why) so dispatch falls back to SIMULATED."""
    env = env if env is not None else os.environ
    if send_mode != "live":
        return (False, "send_mode=%s (not live)" % send_mode)
    tok_env = "PROMO_LIVE_AUTHORIZED_%s" % channel.upper().replace("-", "_")
    val = env.get(tok_env)
    if not val:
        return (False, "missing %s authorize token" % tok_env)
    if expected:
        if not hmac.compare_digest(str(val), str(expected)):
            return (False, "%s does not match configured live_authorize_token" % tok_env)
        return (True, "authorized (token matched)")
    return (True, "authorized (token present)")


def review(payload, *, cfg, channel):
    """Reload permission evidence for the complete actual destination."""
    policy = dict(cfg.policy(channel))
    policy.setdefault('banned_claims', cfg.banned_claims)
    policy.setdefault('physical_address', (cfg.product.get('compliance', {}) or {}).get('physical_address'))
    suppression = compliance.load_suppression(cfg.data_path('metrics', 'suppression.csv'))
    consent = compliance.load_consent_ledger(cfg.data_path('compliance', 'consent-ledger.jsonl'))
    recipient = compliance.normalize_recipient(payload.get('recipient'))
    record = consent.get(recipient) or {}
    if payload.get('audience_mode') == 'owned_broadcast':
        disposition = 'owned channel broadcast; recipient consent ledger does not apply'
    elif str(record.get('status', '')).lower() == 'withdrawn':
        disposition = 'withdrawn; delivery prohibited'
    elif record.get('lawful_basis'):
        disposition = 'current lawful basis: '+str(record['lawful_basis'])
    elif str(payload.get('recipient_country') or '').upper() in compliance.EU_EEA:
        disposition = 'missing required current lawful basis'
    else:
        disposition = 'no consent record; non-EU policy applies'
    eligibility = {'consent': disposition, 'suppressed': bool(recipient and recipient in suppression)}
    ok, reasons = compliance.check(payload, policy=policy, suppression=suppression, consent=consent)
    if payload.get('audience_mode') == 'owned_broadcast' and not payload.get('destination'):
        reasons.append('owned broadcast requires an explicit destination')
    return not reasons, reasons, eligibility, policy


def matching_receipt(receipt, item, status='sent'):
    """Only matching request identity and remote evidence can confirm an action."""
    payload = item.get('payload', item)
    target = payload.get('destination') or payload.get('recipient')
    platform = item.get('platform') or payload.get('platform')
    key = item.get('idempotency_key') or payload.get('idempotency_key')
    if (not isinstance(receipt, dict) or receipt.get('status') != status or not target or not key
            or receipt.get('platform') != platform or receipt.get('idempotency_key') != key):
        return False
    if status == 'sent' and platform == 'email':
        if not email_contract.matching(receipt, payload):
            return False
    if status == 'sent' and platform in {'mastodon', 'bluesky'}:
        reviewed = {**payload, 'account': payload.get('account', item.get('account'))}
        if not providers.matching_owned_identity(receipt, reviewed):
            return False
    elif (receipt.get('destination') or receipt.get('recipient')) != target:
        return False
    evidence = receipt.get('message_id') if status == 'sent' else receipt.get('evidence')
    return isinstance(evidence, str) and bool(evidence.strip())


def reconcile_action(item, *, cfg, env=None):
    """No provider lookup is implemented; uncertainty requires external proof."""
    return {'status': 'unknown', 'reason': 'no authoritative provider reconciliation available'}


def dispatch(decision: dict, *, cfg, throttle, env=None) -> dict:
    """Review, authorize, durably mark intent, then validate the provider receipt."""
    import hashlib
    channel = decision['channel']
    platform = decision.get('platform', channel)
    account = decision.get('account', 'default')
    action = decision.get('action', 'post')
    payload = dict(decision.get('payload', {}))
    payload.setdefault('channel', channel)
    payload.setdefault('platform', platform)
    payload.setdefault('account', account)
    payload.setdefault('destination', payload.get('recipient'))
    payload.setdefault('idempotency_key', decision.get('idempotency_key') or hashlib.sha256(
        json.dumps([decision.get('decision_id'), platform, account, action, payload], sort_keys=True).encode()).hexdigest())
    cfg.metrics_dir()
    events_path = cfg.data_path('metrics', 'events.jsonl')
    dryrun_path = cfg.data_path('metrics', 'dry-run.jsonl')
    ok, reasons, eligibility, policy = review(payload, cfg=cfg, channel=channel)
    reasons = list(decision.get('review_reasons', [])) + reasons
    if payload['account'] != account:
        reasons.append('payload account differs from reviewed decision account')
    channel_config = cfg.channel(channel) or {}
    live, authorization_reason = _authorized(channel, cfg.send_mode, env=env,
                                             expected=cfg.live_authorize_token(channel))
    if channel_config.get('enabled') is False or cfg.product.get('enabled') is False:
        live, authorization_reason = False, 'selected channel or product is disabled'

    def result(status, **extra):
        if not live:
            preview = {'channel': channel, 'platform': platform, 'account': account, 'action': action,
                       'arm_id': decision.get('arm_id'), 'audience_segment': decision.get('audience_segment'),
                       'would_send': payload, 'payload': payload, 'eligibility': eligibility,
                       'status': status, 'reasons': extra.get('reasons', []),
                       'reason_not_live': authorization_reason, 'est_recipients': payload.get('destination')}
            private_storage.update_text(dryrun_path, lambda previous: (
                (previous or '')+json.dumps(preview, ensure_ascii=False)+'\n', None))
        event_type = {'rejected': 'blocked', 'throttled': 'ratelimited'}.get(status, status)
        ev = events.make_event(channel, event_type, platform=platform, account=account,
            arm_id=decision.get('arm_id'), audience_segment=decision.get('audience_segment'),
            decision_id=decision.get('decision_id'), propensity_p=decision.get('propensity_p'),
            policy_version=decision.get('policy_version'), utm=payload.get('utm'),
            live=bool(extra.get('live')), reason=extra.get('reason'))
        events.append_once(events_path, ev, key='dispatch:'+payload['idempotency_key']+':'+event_type)
        return {'status': status, 'payload': payload, 'eligibility': eligibility,
                'safe_to_retry': False, **extra}

    if reasons:
        return result('rejected', stage='compliance', reasons=reasons)
    allow, why, wait = throttle.reserve(
        account, platform, action, policy, reservation_id=payload['idempotency_key'], payload=payload,
        account_stage=channel_config.get('warmup_state', 'normal'))
    if not allow:
        return result('throttled', reason=why, wait_seconds=wait, safe_to_retry=True)
    if not live:
        return result('simulated', live=False, reason=authorization_reason, safe_to_retry=True)
    provider = providers.get(platform)
    if not provider.LIVE_TRANSPORT:
        mode = 'manual-prep' if isinstance(provider, providers.ManualPrepProvider) else 'deferred'
        return result(mode, reason=provider.deferred_reason)
    try:
        before_effect = decision.get('_before_effect')
        if before_effect:
            before_effect()
    except Exception as exc:
        return result('failed', reason='intent persistence failed: '+type(exc).__name__)
    try:
        receipt = (provider.publish(payload, live=True) if action.startswith('post') or action == 'publish'
                   else provider.dm(payload, live=True))
    except Exception as exc:
        return result('uncertain', live=True, reason='provider interrupted: '+type(exc).__name__)
    if isinstance(receipt, dict) and receipt.get('rate_limited') is True:
        # A failed persistence must escape to the run checkpoint and stop further sends.
        throttle.record_throttle_signal(account, platform, action, policy)
    identity = {'payload': payload, 'platform': platform, 'idempotency_key': payload['idempotency_key']}
    if matching_receipt(receipt, identity):
        return result('sent', live=True, provider=receipt, receipt=receipt)
    if matching_receipt(receipt, identity, 'not_applied'):
        return result('failed', provider=receipt, receipt=receipt,
                      reason=receipt.get('reason') or receipt['evidence'], safe_to_retry=True)
    reason = receipt.get('reason') if isinstance(receipt, dict) else None
    return result('uncertain', live=True, provider=receipt, receipt=receipt,
                  reason=reason or 'missing, malformed or mismatched provider acknowledgement')
