"""Draft failure cannot record a completed draft; models and events are fake."""
import sys
from types import SimpleNamespace
import pytest
from scripts import cli


@pytest.mark.parametrize('kind', ['timeout','unknown_effects','empty','exception'])
def test_failed_draft_one_request_no_event(monkeypatch, kind):
    calls = []
    class Result:
        text = ''
        error = kind
        def __bool__(self): return False
    def call(*a, **kw):
        calls.append(kw)
        if kind == 'exception': raise TimeoutError('synthetic')
        return Result()
    monkeypatch.setitem(sys.modules,'llmcall',SimpleNamespace(
        call=call,ModelSelection=lambda:SimpleNamespace(intent='inherit'),
        ExecutionRequirements=lambda **kw:SimpleNamespace(**kw)))
    monkeypatch.setattr(cli,'_load',lambda args:SimpleNamespace(product={},aff_base='https://example.com/',banned_claims=[]))
    from scripts import events
    monkeypatch.setattr(events,'append',lambda *a,**kw:pytest.fail('failed draft wrote event'))
    args = SimpleNamespace(what='draft',graduated=False,aff_code=None,title='synthetic',body='synthetic',intent='help')
    assert cli.cmd_participate(args) == 1
    assert len(calls) == 1
    assert not {'chain','model','effort'} & calls[0].keys()
    assert calls[0]['requirements'].tool_allowlist == ()
    assert calls[0]['requirements'].replay == 'never_after_start'
