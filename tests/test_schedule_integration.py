"""Generated schedule contract regressions. Reproduce with tools/make_fixtures.py."""
import json
import datetime
import subprocess
import sys

import pytest

from scripts import schedule_bridge, orchestrate
from test_review_runs import case


@pytest.fixture
def bridge(tmp_path):
    helper = tmp_path/'reminder.py'
    helper.write_text('# Synthetic subprocess adapter')
    return schedule_bridge.ScheduleBridge(helper, str(tmp_path/'schedule.db'))


def schedule(bridge):
    return bridge.schedule_item(title='Synthetic task', due_at='2026-01-01T00:00:00Z',
                                idempotency_key='synthetic-task', ext={})


@pytest.mark.parametrize('decision', ['create', 'reuse'])
def test_creation_preflight_then_ensure_uses_current_python(bridge, monkeypatch, decision):
    calls = []
    def process(argv, **kwargs):
        calls.append(argv)
        reply = ({'ok': True, 'complete': True, 'decision': decision, 'matches': []}
                 if len(calls) == 1 else {'ok': True, 'item': {'id': 'synthetic-item'}})
        return subprocess.CompletedProcess(argv, 0, json.dumps(reply), '')
    monkeypatch.setattr(subprocess, 'run', process)
    assert schedule(bridge)['item']['id'] == 'synthetic-item'
    assert [call[2] for call in calls] == ['creation-preflight', 'ensure']
    assert all(call[0] == sys.executable for call in calls)
    assert calls[0][3:] == calls[1][3:]


@pytest.mark.parametrize('receipt', [
    {'ok': True, 'decision': 'create', 'complete': False, 'matches': []},
    {'ok': True},
])
def test_incomplete_preflight_never_creates(bridge, monkeypatch, receipt):
    calls = []
    def process(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, json.dumps(receipt), '')
    monkeypatch.setattr(subprocess, 'run', process)
    result = schedule(bridge)
    assert result['ok'] is False
    assert result['error_code'] == 'ERR_CREATION_REVIEW'
    assert len(calls) == 1


def test_schedule_preserves_structured_helper_failure(bridge, monkeypatch):
    error = {'ok': False, 'error_code': 'ERR_CREATION_REVIEW', 'message': 'Review candidates'}
    monkeypatch.setattr(subprocess, 'run', lambda argv, **kw:
                        subprocess.CompletedProcess(argv, 1, '', json.dumps(error)))
    assert schedule(bridge) == error


def test_progress_uses_frozen_state_contract(bridge, monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, 'run', lambda argv, **kw:
                        (calls.append(argv) or subprocess.CompletedProcess(
                            argv, 0, json.dumps({'ok': True, 'item': {'id': 'synthetic-item'}}), '')))
    assert bridge.progress('synthetic-item', 'review')['ok'] is True
    assert calls[0][calls[0].index('--to')+1] == 'doing'


def test_helper_environment_is_resolved_at_construction(bridge, monkeypatch):
    monkeypatch.setenv('PROMO_REMINDER_PY', str(bridge.reminder))
    assert schedule_bridge.ScheduleBridge().reminder == bridge.reminder


def test_review_preflight_preserves_transactional_replay(bridge, monkeypatch):
    calls = []
    def process(argv, **kwargs):
        calls.append(argv)
        reply = ({'ok': True, 'decision': 'review', 'complete': True, 'matches': []}
                 if len(calls) == 1 else
                 {'ok': True, 'decision': 'replayed', 'item': {'id': 'synthetic-item', 'state': 'done'}})
        return subprocess.CompletedProcess(argv, 0, json.dumps(reply), '')
    monkeypatch.setattr(subprocess, 'run', process)
    assert schedule(bridge)['item']['state'] == 'done'
    assert [call[2] for call in calls] == ['creation-preflight', 'ensure']


class CaptureBridge:
    def __init__(self):
        self.calls = []
    def available(self):
        return True
    def schedule_item(self, **request):
        self.calls.append(request)
        return {'ok': True, 'item': {'id': request['idempotency_key']}}


def test_plan_retry_preserves_original_request_across_clock_changes(case):
    bridge = CaptureBridge()
    start = datetime.datetime(2026, 1, 1, 10)
    assert orchestrate.plan(case['cfg'], case['campaign'], start=start, bridge=bridge)['scheduled'] == 1
    assert orchestrate.plan(case['cfg'], case['campaign'], start=start+datetime.timedelta(hours=1),
                            bridge=bridge)['scheduled'] == 1
    assert bridge.calls[0] == bridge.calls[1]
    assert len(list((case['root']/'metrics/schedule-requests').glob('*.json'))) == 1


def test_plan_changes_cannot_overwrite_existing_occurrence(case):
    bridge = CaptureBridge()
    start = datetime.datetime(2026, 1, 1, 10)
    orchestrate.plan(case['cfg'], case['campaign'], start=start, bridge=bridge)
    arms = [dict(case['arms'][0], hook='Revised synthetic announcement')]
    (case['root']/'copy'/(case['campaign']+'.json')).write_text(json.dumps(arms))
    result = orchestrate.plan(case['cfg'], case['campaign'], start=start, bridge=bridge)
    assert result['status'] == 'failed'
    assert result['errors'][0]['error_code'] == 'ERR_SCHEDULE_CHANGED'
    assert len(bridge.calls) == 1


def test_corrupt_schedule_snapshot_stops_before_helper(case):
    bridge = CaptureBridge()
    start = datetime.datetime(2026, 1, 1, 10)
    orchestrate.plan(case['cfg'], case['campaign'], start=start, bridge=bridge)
    snapshot = next((case['root']/'metrics/schedule-requests').glob('*.json'))
    snapshot.write_text('{}')
    result = orchestrate.plan(case['cfg'], case['campaign'], start=start, bridge=bridge)
    assert result['status'] == 'failed'
    assert result['errors'][0]['error_code'] == 'ERR_SCHEDULE_CHANGED'
    assert len(bridge.calls) == 1
