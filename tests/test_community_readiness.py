"""Generated synthetic community-readiness regressions; see tools/make_fixtures.py."""
import pytest

from scripts import cli, events, orchestrate, participation
from test_review_runs import case


def record(case, community, *, kind='give', count=9):
    for index in range(count):
        thread = 'https://www.reddit.com/r/%s/comments/%s%d/topic' % (community, kind, index)
        result = orchestrate.record_participation(
            case['cfg'], thread+'/comment', thread=thread, participation_type=kind)
        assert result['status'] == 'recorded'


def status(case, capsys, community):
    argv = ['--config', str(case['root']), 'participate', 'status',
            '--age-days', '30', '--karma', '100', '--strikes', '0']
    if community is not None:
        argv.extend(['--sub', community])
    result = cli.main(argv)
    return result, capsys.readouterr()


def test_nine_gives_elsewhere_do_not_graduate_target_community(case, capsys):
    record(case, 'community_alpha')
    result, output = status(case, capsys, 'community_beta')
    assert result == 0
    assert '=> NOT READY' in output.out
    assert '0 gives / 0 asks' in output.out
    assert 'contributions >= 3 (have: 0)' in output.out
    assert 'r/community_beta' in output.out


@pytest.mark.parametrize('target', ['community_alpha', 'r/Community_Alpha', '/r/COMMUNITY_ALPHA/'])
def test_target_normalization_preserves_matching_contributions(case, capsys, target):
    record(case, 'Community_Alpha')
    result, output = status(case, capsys, target)
    assert result == 0 and '=> READY' in output.out
    assert '9 gives / 0 asks' in output.out
    assert 'r/community_alpha' in output.out


def test_other_community_gives_cannot_cover_target_asks(case, capsys):
    record(case, 'community_alpha')
    record(case, 'community_beta', count=3)
    record(case, 'community_beta', kind='ask', count=1)
    result, output = status(case, capsys, 'community_beta')
    assert result == 0 and '=> NOT READY' in output.out
    assert '3 gives / 1 asks' in output.out and '9:1 NOT held' in output.out


def test_other_community_asks_do_not_change_target_ledger(case, capsys):
    record(case, 'community_alpha')
    record(case, 'community_beta', kind='ask')
    result, output = status(case, capsys, 'community_alpha')
    assert result == 0 and '=> READY' in output.out
    assert '9 gives / 0 asks' in output.out


@pytest.mark.parametrize('target', [None, '', 'community alpha', 'r/',
                                   'community_alpha/other', 'https://example.com'])
def test_status_requires_one_valid_target_community(case, capsys, target):
    record(case, 'community_alpha')
    result, output = status(case, capsys, target)
    assert result == 2 and '--sub' in output.err
    assert '=> READY' not in output.out


@pytest.mark.parametrize('host', ['reddit.com', 'www.reddit.com', 'old.reddit.com', 'np.reddit.com'])
def test_confirmed_entries_retain_normalized_context(host):
    url = 'https://%s/r/Community_Alpha/comments/abc/topic/comment' % host
    thread = participation.thread_identity(url)
    row = {'channel': 'reddit-participation', 'event_type': 'sent', 'actuator': 'human',
           'live': True, 'participation_type': 'give', 'post_url': url, 'thread': thread}
    entry, = participation.confirmed_entries([row])
    assert entry['community'] == 'community_alpha'
    assert entry['thread'] == thread
    repeated = {**row, 'post_url': url+'?utm_source=synthetic'}
    assert len(participation.confirmed_entries([row, repeated])) == 1


@pytest.mark.parametrize('location', ['https://www.reddit.com/comments/abc/topic',
                                      'https://example.com/r/community_alpha/comments/abc/topic'])
def test_legacy_unknown_community_stays_readable_without_readiness_credit(case, capsys, location):
    path = case['root']/'metrics/events.jsonl'
    for index in range(9):
        events.append(path, events.make_event(
            'reddit-participation', 'sent', platform='reddit', actuator='human', live=True,
            participation_type='give', post_url=location+'/comment%d' % index))
    entries = participation.confirmed_entries(events.read(path))
    assert len(entries) == 9
    assert all(entry['community'] is None for entry in entries)
    result, output = status(case, capsys, 'community_alpha')
    assert result == 0 and '=> NOT READY' in output.out
    assert '0 gives / 0 asks' in output.out



@pytest.mark.parametrize('gives, asks, ready', [(3, 0, False), (8, 0, False),
                                              (9, 1, False), (9, 0, True), (18, 1, True)])
def test_readiness_requires_room_for_the_next_promotional_post(gives, asks, ready):
    ledger = [{'type': 'give'}] * gives + [{'type': 'ask'}] * asks
    result = participation.readiness(
        {'age_days': 30, 'karma': 100, 'sub_gives': gives, 'mod_strikes': 0}, ledger)
    assert result['ready'] is ready
    assert result['ledger']['next_ask_ok'] is ready
    criterion = next(item for item in result['criteria'] if item['key'] == 'ledger_9to1')
    assert criterion['met'] is ready and 'next promotional post' in criterion['detail']


@pytest.mark.parametrize('gives, asks, ready', [(3, 0, False), (8, 0, False),
                                              (9, 1, False), (9, 0, True), (18, 1, True)])
def test_cli_readiness_labels_the_next_promotional_allowance(case, capsys, gives, asks, ready):
    record(case, 'community_alpha', count=gives)
    record(case, 'community_alpha', kind='ask', count=asks)
    result, output = status(case, capsys, 'community_alpha')
    assert result == 0
    assert ('=> READY' if ready else '=> NOT READY') in output.out
    assert 'next promotional post' in output.out
