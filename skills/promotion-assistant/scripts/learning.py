"""Credit linked observations once, with receipts in the same atomic posterior update."""
import hashlib
import json

from . import bandit, metrics, private_storage


def _observations(rows):
    observations = {}
    for row in rows:
        if (not isinstance(row, dict) or not isinstance(row.get('event_id'), str)
                or not row['event_id'] or not isinstance(row.get('decision_id'), str)
                or not row['decision_id'] or not isinstance(row.get('arm_id'), str)
                or not row['arm_id']):
            continue
        if row.get('event_type') not in {*metrics.DEFAULT_REWARD_WEIGHTS, 'sent', 'simulated'}:
            continue
        binding = hashlib.sha256(json.dumps(row, sort_keys=True, separators=(',', ':'),
                                            allow_nan=False).encode()).hexdigest()
        key = row['event_id']
        if key in observations and observations[key][1] != binding:
            raise ValueError('observation identity has conflicting content')
        observations[key] = (row, binding)
    return observations


def credit_observations(path, rows, *, arm_id, decision_ids, conversion_window_s=None, now=None):
    """Only new event identities linked to this run can update the selected arm.

    A legacy posterior has no credit receipts. Its existing observations are baselined without
    changing the posterior, so migration never knowingly credits historical evidence again.
    Censored observations wait for a new linked event; a status-only resume cannot mature them.
    """
    observations = _observations(rows)
    decisions = set(decision_ids)
    if not isinstance(arm_id, str) or not arm_id or not decisions or any(
            not isinstance(item, str) or not item for item in decisions):
        raise ValueError('reward accounting requires the saved arm and decision identities')

    def receipt(row, binding, status):
        return {'binding': binding, 'decision_id': row['decision_id'],
                'arm_id': row['arm_id'], 'status': status}

    def update(previous):
        document = bandit.decode_state(previous)
        if previous is not None and 'observation_credits' not in document:
            document['observation_credits'] = {
                key: receipt(row, binding, 'legacy-observed')
                for key, (row, binding) in observations.items()}
            return json.dumps(document, indent=2, sort_keys=True)+'\n', (None, 'legacy-baseline-established')
        credits = document.setdefault('observation_credits', {})
        for key, (row, binding) in observations.items():
            if key in credits and credits[key] != receipt(row, binding, credits[key]['status']):
                raise ValueError('credited observation identity changed')
        relevant = {key: pair for key, pair in observations.items()
                    if pair[0]['arm_id'] == arm_id and pair[0]['decision_id'] in decisions}
        incoming = {key for key in relevant if key not in credits}
        if not incoming:
            return previous, (None, 'no-new-observations')
        learner = bandit.Bandit(None)
        learner.arms = document['arms']
        rewards = []
        pending = False
        for decision in sorted(decisions):
            group = {key: pair for key, pair in relevant.items()
                     if pair[0]['decision_id'] == decision
                     and (key not in credits or credits[key]['status'] == 'censored')}
            if not incoming.intersection(group):
                continue
            reward, status = metrics.reward_for_arm(
                [row for row, _ in group.values()], arm_id,
                conversion_window_s=conversion_window_s, now=now)
            if reward is not None:
                learner._discount()
                learner.update(arm_id, reward)
                rewards.append(reward)
            else:
                pending = True
            for key, (row, binding) in group.items():
                credits[key] = receipt(row, binding, 'credited' if reward is not None else 'censored')
        document.update(policy_version=bandit.POLICY_VERSION, arms=learner.arms)
        outcome = (sum(rewards)/len(rewards), 'ok') if rewards else (None, 'censored' if pending else 'no-data')
        return json.dumps(document, indent=2, sort_keys=True)+'\n', outcome

    return private_storage.update_text(path, update)
