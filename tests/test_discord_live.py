"""E23 -- DiscordOwnServerProvider live publish (own-server announce via REST bot).

Live network is never touched: urlopen is mocked. Verifies the two-switch contract still holds
(live=False stays a deferred-gap), credentials are required, a real 200 maps to 'sent', a 429 maps
to 'throttled' so the caller's AIMD can react, and other HTTP errors surface as 'error'.
"""
import io
import json
import urllib.error
from unittest import mock

from scripts import providers as P


def _resp(obj):
    m = mock.MagicMock()
    m.read.return_value = json.dumps(obj).encode("utf-8")
    m.__enter__.return_value = m
    m.__exit__.return_value = False
    return m


def _http_error(code, body="{}"):
    return urllib.error.HTTPError("u", code, "err", {}, io.BytesIO(body.encode("utf-8")))


PAYLOAD = {"subject": "New free models live", "body": "changelog here", "cta": "https://x/register?aff=a"}


def test_not_live_is_deferred_gap():
    r = P.DiscordOwnServerProvider().publish(PAYLOAD, live=False)
    assert r["status"] == "deferred-gap"


def test_missing_credentials_errors(monkeypatch):
    monkeypatch.delenv("PROMO_DISCORD_BOT_TOKEN", raising=False)
    monkeypatch.delenv("PROMO_DISCORD_ANNOUNCE_CHANNEL_ID", raising=False)
    r = P.DiscordOwnServerProvider().publish(PAYLOAD, live=True)
    assert r["status"] == "error" and "not in env" in r["reason"]


def test_non_numeric_channel_rejected(monkeypatch):
    monkeypatch.setenv("PROMO_DISCORD_BOT_TOKEN", "tok")
    monkeypatch.setenv("PROMO_DISCORD_ANNOUNCE_CHANNEL_ID", "not-a-number")
    r = P.DiscordOwnServerProvider().publish(PAYLOAD, live=True)
    assert r["status"] == "error" and "numeric" in r["reason"]


def test_live_success_maps_to_sent(monkeypatch):
    monkeypatch.setenv("PROMO_DISCORD_BOT_TOKEN", "tok")
    monkeypatch.setenv("PROMO_DISCORD_ANNOUNCE_CHANNEL_ID", "123456789")
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["auth"] = req.headers.get("Authorization")
        captured["body"] = json.loads(req.data.decode("utf-8"))["content"]
        return _resp({"id": "999"})

    with mock.patch.object(P.urllib.request, "urlopen", fake_urlopen):
        r = P.DiscordOwnServerProvider().publish(PAYLOAD, live=True)
    assert r["status"] == "sent" and r["message_id"] == "999" and r["channel_id"] == "123456789"
    assert captured["url"].endswith("/channels/123456789/messages")
    assert captured["auth"] == "Bot tok"
    # message composes subject (bold) + body + cta, and carries the affiliate CTA
    assert "**New free models live**" in captured["body"] and "aff=a" in captured["body"]


def test_empty_message_errors(monkeypatch):
    monkeypatch.setenv("PROMO_DISCORD_BOT_TOKEN", "tok")
    monkeypatch.setenv("PROMO_DISCORD_ANNOUNCE_CHANNEL_ID", "123")
    r = P.DiscordOwnServerProvider().publish({"subject": "", "body": "", "cta": ""}, live=True)
    assert r["status"] == "error" and "empty" in r["reason"]


def test_429_maps_to_throttled(monkeypatch):
    monkeypatch.setenv("PROMO_DISCORD_BOT_TOKEN", "tok")
    monkeypatch.setenv("PROMO_DISCORD_ANNOUNCE_CHANNEL_ID", "123")
    with mock.patch.object(P.urllib.request, "urlopen", side_effect=_http_error(429, '{"retry_after":2}')):
        r = P.DiscordOwnServerProvider().publish(PAYLOAD, live=True)
    assert r["status"] == "throttled"


def test_403_maps_to_error(monkeypatch):
    monkeypatch.setenv("PROMO_DISCORD_BOT_TOKEN", "tok")
    monkeypatch.setenv("PROMO_DISCORD_ANNOUNCE_CHANNEL_ID", "123")
    with mock.patch.object(P.urllib.request, "urlopen", side_effect=_http_error(403, '{"message":"Missing Access"}')):
        r = P.DiscordOwnServerProvider().publish(PAYLOAD, live=True)
    assert r["status"] == "error" and r["code"] == 403
