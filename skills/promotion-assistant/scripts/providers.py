#!/usr/bin/env python3
"""L2 channel adapters — one provider per platform, uniform interface.

Interface: publish(payload) / engage(payload) / dm(payload) / read_metrics(...).
Each provider, in LIVE mode, processes its own OAuth + reacts to runtime rate-limit headers
(RateLimit-*/Retry-After/429) — the quota TABLE is hot-swappable config, never hardcoded.

BUILD-TIME REALITY: every live transport here is gated behind dispatch.py's fail-closed exit,
so calling a provider during build/test produces a SIMULATED result (no network egress). The
provider classes carry a `LIVE_TRANSPORT` flag: True = a real integration path exists (email via
the local send-gmail.ps1 link; Discord via the relay/own-server bot), False = deferred-gap (the
demand-side primitive is registered but no compliant automated transport ships yet — e.g. Reddit
OAuth posting and X API). A deferred-gap is an EXPLICIT gap, never a silent skip.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

if __package__:
    from . import email_contract
else:
    from scripts import email_contract

_SELECTED_ENV = ContextVar('promotion_selected_resources', default=None)


@contextmanager
def runtime_environment(environment):
    token = _SELECTED_ENV.set(dict(environment))
    try:
        yield
    finally:
        _SELECTED_ENV.reset(token)


def _environment():
    selected = _SELECTED_ENV.get()
    return os.environ if selected is None else selected


# Local infra contracts (reused, not reimplemented). Paths are env-configurable for portability;
# defaults are generic per-tool locations, never hardcoded personal install paths.
SEND_GMAIL_PS1 = Path(os.path.expanduser(
    os.environ.get("PROMO_SEND_GMAIL", "~/.local/send-gmail.ps1")))
DISCORD_RELAY = Path(os.path.expanduser(
    os.environ.get("PROMO_NOTIFIER_PY", "~/.local/notifier.py")))

# A single, well-formed email recipient (no whitespace/quotes/angle-brackets, exactly one @).
_EMAIL_RE = re.compile(r"^[^\s@\"'<>]+@[^\s@\"'<>]+\.[^\s@\"'<>]+$")


def _arg_binding_safe(*vals) -> bool:
    """Reject any positional value that would be mis-bound as a PARAMETER NAME by
    `powershell -File ... -To <val>` (PowerShell treats a leading '-' token as a param name,
    not a value). Not shell injection (no shell=True) but a real arg-binding vector on the
    live email path. Live-only + operator-controlled config, so this is defense-in-depth."""
    return not any(isinstance(v, str) and v.startswith("-") for v in vals)


def _receipt(payload, platform, remote_id, *, destination=None, **extra):
    if not isinstance(remote_id, str) or not remote_id.strip():
        return {'status': 'uncertain', 'platform': platform, 'reason': 'response lacked a remote message ID'}
    target = payload.get('destination') or payload.get('recipient') or destination
    key = payload.get('idempotency_key') or hashlib.sha256(
        json.dumps([platform, target, payload], sort_keys=True).encode()).hexdigest()
    return {**extra, 'status': 'sent', 'platform': platform, 'idempotency_key': key,
            'destination': target, 'message_id': remote_id}


def _not_applied(payload, platform, reason):
    return {'status': 'not_applied', 'platform': platform,
            'idempotency_key': payload.get('idempotency_key'),
            'destination': payload.get('destination') or payload.get('recipient'),
            'evidence': 'No publish request was made: '+reason, 'reason': reason}


_DID_RE = re.compile(r'did:[a-z0-9]+:[A-Za-z0-9._:%-]+')
_POST_URI_RE = re.compile(r'at://(did:[a-z0-9]+:[A-Za-z0-9._:%-]+)/app\.bsky\.feed\.post/[A-Za-z0-9._~:-]+')


def _handle(value):
    if not isinstance(value, str):
        return ''
    value = value.strip().lstrip('@')
    return value if value.startswith('did:') else value.lower()


def _https_url(value):
    if not isinstance(value, str) or any(char.isspace() for char in value) or '\\' in value:
        raise ValueError('invalid identity URL')
    parsed = urllib.parse.urlsplit(value)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment):
        raise ValueError('identity URL must be an absolute HTTPS URL without credentials or suffixes')
    return 'https://' + parsed.netloc.lower() + parsed.path.rstrip('/')


def _origin(value):
    parsed = urllib.parse.urlsplit(_https_url(value))
    return 'https://' + parsed.netloc


def _mastodon_identity(account, instance):
    if not isinstance(account, dict):
        raise ValueError('Mastodon response lacked account identity')
    account_id, username = account.get('id'), _handle(account.get('username'))
    if not isinstance(account_id, str) or not account_id.strip() or not re.fullmatch(r'[a-z0-9_]+', username):
        raise ValueError('Mastodon response lacked account ID or username')
    host = urllib.parse.urlsplit(instance).netloc
    acct = _handle(account.get('acct'))
    url = _https_url(account.get('url'))
    if (acct not in {username, username + '@' + host} or _origin(url) != instance
            or urllib.parse.urlsplit(url).path not in {'/@' + username, '/users/' + username}):
        raise ValueError('Mastodon account fields disagree with the configured instance')
    return {'account': username + '@' + host, 'account_id': account_id,
            'destination': url, 'instance': instance}


def _bluesky_target(value):
    if isinstance(value, str) and value.startswith('https://'):
        url = _https_url(value)
        prefix = 'https://bsky.app/profile/'
        if not url.startswith(prefix):
            return ''
        value = url[len(prefix):]
    return _handle(value)


def matching_owned_identity(receipt, payload):
    """Compare reviewed intent with observed provider identity, including its destination."""
    try:
        account, destination = payload.get('account'), payload.get('destination')
        if receipt.get('platform') == 'bluesky':
            handle, repo = _handle(receipt.get('account')), receipt.get('repository')
            if 'message_id' in receipt:
                uri = receipt['message_id']
                match = _POST_URI_RE.fullmatch(uri) if isinstance(uri, str) else None
                if not match or match.group(1) != repo:
                    return False
            return (bool(handle) and isinstance(repo, str) and bool(_DID_RE.fullmatch(repo))
                    and receipt.get('destination') == repo
                    and _handle(account) in {handle, repo}
                    and _bluesky_target(destination) in {handle, repo})
        if receipt.get('platform') == 'mastodon':
            observed = receipt.get('account')
            instance, profile = _https_url(receipt.get('instance')), _https_url(receipt.get('destination'))
            if not isinstance(observed, str) or '@' not in observed or _origin(profile) != instance:
                return False
            username, host = observed.rsplit('@', 1)
            if host != urllib.parse.urlsplit(instance).netloc or _handle(account) not in {username, observed}:
                return False
            if 'message_id' in receipt:
                message_id, account_id = receipt['message_id'], receipt.get('account_id')
                if not all(isinstance(value, str) and value.strip() for value in (message_id, account_id)):
                    return False
                if _https_url(receipt.get('url')) not in {profile + '/' + message_id,
                                                          instance + '/@' + username + '/' + message_id}:
                    return False
            return (_https_url(destination) == profile if isinstance(destination, str) and destination.startswith('https://')
                    else _handle(destination) == observed)
    except (ValueError, TypeError):
        return False
    return False


def _owned_receipt(payload, platform, remote_id, identity):
    """Keep remote identity; never fill missing provider evidence from the request."""
    receipt = {**identity, 'platform': platform, 'idempotency_key': payload.get('idempotency_key'),
               'message_id': remote_id}
    valid = (isinstance(remote_id, str) and bool(remote_id.strip())
             and matching_owned_identity(receipt, payload))
    return {**receipt, 'status': 'sent' if valid else 'uncertain',
            **({} if valid else {'reason': 'remote account or destination did not confirm reviewed intent'})}


class Provider:
    platform = "base"
    LIVE_TRANSPORT = False          # subclasses flip to True when a compliant path exists
    deferred_reason = "no compliant automated transport implemented yet"

    def publish(self, payload, *, live=False):
        return self._not_live("publish")

    def engage(self, payload, *, live=False):
        return self._not_live("engage")

    def dm(self, payload, *, live=False):
        return self._not_live("dm")

    def read_metrics(self, **kw):
        return {"status": "deferred", "reason": self.deferred_reason}

    def _not_live(self, action):
        return {"status": "deferred-gap", "platform": self.platform,
                "action": action, "reason": self.deferred_reason}


class EmailProvider(Provider):
    """Invoke only the explicitly configured reviewed-email-v1 JSON helper contract."""
    platform = "email"
    LIVE_TRANSPORT = True
    deferred_reason = "email helper requires reviewed-email-v1 request and receipt support"

    def publish(self, payload, *, live=False):
        if not live:
            return self._not_live("publish")
        selected = _SELECTED_ENV.get()
        helper = (Path(selected.get('PROMO_SEND_GMAIL', '')).expanduser()
                  if selected is not None else SEND_GMAIL_PS1)
        if not helper.is_file():
            return _not_applied(payload, self.platform, 'email helper not found; initialize reviewed-email-v1 support')
        if not _arg_binding_safe(payload.get('recipient'), payload.get('subject'), payload.get('body')):
            return _not_applied(payload, self.platform, 'argument starts with a dash; conservative binding guard')
        try:
            request = email_contract.request(payload)
        except (ValueError, TypeError) as exc:
            return _not_applied(payload, self.platform, str(exc))
        # All values travel in one JSON argument. The helper must verify request_sha256 and
        # return observed sender/content evidence; legacy -To/-Subject/-Body helpers are unsupported.
        cmd = ["powershell", "-NoProfile", "-File", str(helper),
               "-RequestJson", json.dumps(request, ensure_ascii=False)]
        try:
            response = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                                      errors="strict", timeout=60)
            if response.returncode != 0:
                return {'status': 'uncertain', 'reason': 'email helper exited without a confirmed outcome',
                        'rc': response.returncode}
            receipt = json.loads(response.stdout or '')
            if not email_contract.matching(receipt, payload):
                return {'status': 'uncertain', 'reason': 'email helper did not confirm the complete frozen request'}
            return receipt
        except Exception as exc:
            return {'status': 'uncertain', 'reason': 'email helper outcome unavailable: '+type(exc).__name__}

    def dm(self, payload, *, live=False):
        return self.publish(payload, live=live)


class DiscordOwnServerProvider(Provider):
    """Announcements to OWN Discord server via a dedicated server-scoped bot. Cross-server stranger
    auto-DM and selfbots are FORBIDDEN (instant ban) — only own-channel + official bot are compliant.

    Live path: a server-scoped promo bot (SEPARATE from the alert relay bot) posts one message to a
    configured announce channel via the Discord REST API. Credentials come from the channel secret
    (env, never the repo): PROMO_DISCORD_BOT_TOKEN + PROMO_DISCORD_ANNOUNCE_CHANNEL_ID. Reaching this
    method already means dispatch.py cleared compliance + throttle + BOTH live switches."""
    platform = "discord"
    LIVE_TRANSPORT = True
    deferred_reason = "own-server bot path implemented; set PROMO_DISCORD_BOT_TOKEN + channel to go live"
    API = "https://discord.com/api/v10"

    def publish(self, payload, *, live=False):
        if not live:
            return self._not_live("publish")
        token = _environment().get("PROMO_DISCORD_BOT_TOKEN", "").strip()
        channel_id = _environment().get("PROMO_DISCORD_ANNOUNCE_CHANNEL_ID", "").strip()
        if not token or not channel_id:
            return _not_applied(payload, self.platform, 'PROMO_DISCORD_BOT_TOKEN / PROMO_DISCORD_ANNOUNCE_CHANNEL_ID not in env')
        if not channel_id.isdigit():
            return _not_applied(payload, self.platform, 'Discord channel must be a numeric id')
        if payload.get('destination') and payload['destination'] != channel_id:
            return _not_applied(payload, self.platform, 'reviewed Discord destination differs from configured channel')
        parts = [p for p in (
            (f"**{payload.get('subject').strip()}**" if payload.get("subject") else None),
            (payload.get("body") or "").strip() or None,
            (payload.get("cta") or "").strip() or None,
        ) if p]
        content = "\n\n".join(parts)
        if len(content) > 2000:
            return _not_applied(payload, self.platform, 'reviewed content exceeds Discord message limit')
        if not content:
            return _not_applied(payload, self.platform, 'empty message (no subject/body/cta)')
        # Suppress Discord's auto link-preview card by default: these are frequent changelog posts, and
        # a big unfurled website card on every one is noisy -- a clickable link is enough. flags=4 is
        # SUPPRESS_EMBEDS. Set PROMO_DISCORD_ALLOW_EMBED=1 for a rare launch post that wants the card.
        body = {"content": content}
        if not _environment().get("PROMO_DISCORD_ALLOW_EMBED", "").strip():
            body["flags"] = 4
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            f"{self.API}/channels/{channel_id}/messages", data=data, method="POST",
            headers={"Authorization": f"Bot {token}", "Content-Type": "application/json",
                     "User-Agent": "promotion-assistant (https://github.com/DaizeDong/promotion-assistant, 0.1)"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                resp = json.loads(r.read().decode("utf-8"))
            return _receipt(payload, self.platform, resp.get('id') if isinstance(resp, dict) else None,
                            destination=channel_id, channel_id=channel_id)
        except urllib.error.HTTPError as e:
            detail = (e.read().decode("utf-8", "replace") or "")[:200]
            if e.code == 429:  # let the caller's AIMD throttle react to a real rate-limit
                return {"status": "throttled", "rate_limited": True, "reason": "discord 429", "detail": detail}
            return {"status": "error", "code": e.code, "reason": detail}
        except Exception as e:  # pragma: no cover (live-only network)
            return {"status": "error", "reason": str(e)[:200]}


class MastodonProvider(Provider):
    """Posts to an OWNED Mastodon account's OWN timeline (a compliant self-broadcast for the secondary
    indie-dev ICP). NO auto-follow, NO reply-spam, NO DMing strangers -- only your own toot. Creds from
    env (never repo): PROMO_MASTODON_INSTANCE (e.g. https://mastodon.social) + PROMO_MASTODON_TOKEN (an
    app access token from Preferences > Development). Reaching publish() already means dispatch.py
    cleared compliance + throttle + BOTH live switches. Instance rules on promo vary -- vet them first."""
    platform = "mastodon"
    LIVE_TRANSPORT = True
    deferred_reason = "Mastodon REST implemented; set PROMO_MASTODON_INSTANCE + PROMO_MASTODON_TOKEN to go live"

    def publish(self, payload, *, live=False):
        if not live:
            return self._not_live("publish")
        instance = _environment().get("PROMO_MASTODON_INSTANCE", "").strip().rstrip("/")
        token = _environment().get("PROMO_MASTODON_TOKEN", "").strip()
        if not instance or not token:
            return _not_applied(payload, self.platform, 'PROMO_MASTODON_INSTANCE / PROMO_MASTODON_TOKEN not in env')
        parts = [p for p in ((payload.get("subject") or "").strip(), (payload.get("body") or "").strip(),
                             (payload.get("cta") or "").strip()) if p]
        status = "\n\n".join(parts)
        if len(status) > 500:
            return _not_applied(payload, self.platform, 'reviewed content exceeds default Mastodon limit')
        if not status:
            return _not_applied(payload, self.platform, 'empty status')
        try:
            instance = _https_url(instance)
            reviewed_account = _handle(payload.get('account'))
            username = reviewed_account.split('@', 1)[0]
            host = urllib.parse.urlsplit(instance).netloc
            if (instance != _origin(instance) or not re.fullmatch(r'[a-z0-9_]+', username)
                    or reviewed_account not in {username, username + '@' + host}):
                raise ValueError('reviewed Mastodon account differs from configured instance')
            target = payload.get('destination')
            if isinstance(target, str) and target.startswith('https://'):
                target = _https_url(target)
                if target not in {instance + '/@' + username, instance + '/users/' + username}:
                    raise ValueError('reviewed Mastodon destination differs from configured instance/account')
            elif _handle(target) != username + '@' + host:
                raise ValueError('reviewed Mastodon destination must identify the owned account')
            verify = urllib.request.Request(
                f'{instance}/api/v1/accounts/verify_credentials',
                headers={'Authorization': f'Bearer {token}'})
            with urllib.request.urlopen(verify, timeout=30) as response:
                authenticated = _mastodon_identity(json.loads(response.read().decode('utf-8')), instance)
            if not matching_owned_identity({'platform': self.platform, **authenticated}, payload):
                raise ValueError('authenticated Mastodon account differs from reviewed account/destination')
        except Exception as exc:
            receipt = _not_applied(payload, self.platform, 'Mastodon identity preflight failed: ' + type(exc).__name__)
            if isinstance(exc, urllib.error.HTTPError) and exc.code == 429:
                receipt.update(rate_limited=True, code=429)
            return receipt
        data = json.dumps({"status": status, "visibility": "public"}).encode("utf-8")
        req = urllib.request.Request(
            f"{instance}/api/v1/statuses", data=data, method="POST",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                     "Idempotency-Key": hashlib.sha256(str(payload.get('idempotency_key') or status).encode()).hexdigest(),
                     "User-Agent": "promotion-assistant (+https://github.com/DaizeDong/promotion-assistant)"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                resp = json.loads(r.read().decode("utf-8"))
            observed = _mastodon_identity(resp.get('account'), instance)
            receipt = _owned_receipt(payload, self.platform, resp.get('id'), {**observed, 'url': resp.get('url')})
            if observed != authenticated or _origin(receipt['url']) != instance:
                receipt.update(status='uncertain', reason='Mastodon post response disagrees with authenticated identity')
            return receipt
        except urllib.error.HTTPError as e:
            detail = (e.read().decode("utf-8", "replace") or "")[:200]
            if e.code == 429:
                return {"status": "throttled", "rate_limited": True, "reason": "mastodon 429", "detail": detail}
            return {"status": "error", "code": e.code, "reason": detail}
        except Exception as e:  # pragma: no cover (live-only network)
            return {"status": "uncertain", "reason": 'Mastodon publish response was not confirmed: ' + type(e).__name__}


class BlueskyProvider(Provider):
    """Posts to an OWNED Bluesky account's OWN feed via the AT Protocol (compliant self-broadcast).
    Auth uses an APP PASSWORD (Settings > App Passwords), NEVER the main password. Creds from env:
    PROMO_BLUESKY_HANDLE (you.bsky.social) + PROMO_BLUESKY_APP_PASSWORD. Two-step: create a session
    (com.atproto.server.createSession) then create a post record. Reaching publish() already means
    dispatch.py cleared compliance + throttle + BOTH live switches."""
    platform = "bluesky"
    LIVE_TRANSPORT = True
    deferred_reason = "Bluesky AT-proto implemented; set PROMO_BLUESKY_HANDLE + PROMO_BLUESKY_APP_PASSWORD to go live"
    PDS = "https://bsky.social"

    def _session(self, handle, app_pw):
        data = json.dumps({"identifier": handle, "password": app_pw}).encode("utf-8")
        req = urllib.request.Request(f"{self.PDS}/xrpc/com.atproto.server.createSession",
                                     data=data, method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))

    def publish(self, payload, *, live=False):
        if not live:
            return self._not_live("publish")
        handle = _environment().get("PROMO_BLUESKY_HANDLE", "").strip()
        app_pw = _environment().get("PROMO_BLUESKY_APP_PASSWORD", "").strip()
        if not handle or not app_pw:
            return _not_applied(payload, self.platform, 'PROMO_BLUESKY_HANDLE / PROMO_BLUESKY_APP_PASSWORD not in env')
        parts = [p for p in ((payload.get("subject") or "").strip(), (payload.get("body") or "").strip(),
                             (payload.get("cta") or "").strip()) if p]
        text = "\n\n".join(parts)
        if len(text) > 300:
            return _not_applied(payload, self.platform, 'reviewed content exceeds Bluesky limit')
        if not text:
            return _not_applied(payload, self.platform, 'empty post')
        try:
            handle = _handle(handle)
            reviewed_account = _handle(payload.get('account'))
            target = _bluesky_target(payload.get('destination'))
            if (reviewed_account != handle and not _DID_RE.fullmatch(reviewed_account)):
                raise ValueError('reviewed Bluesky account differs from configured handle')
            if target != handle and not _DID_RE.fullmatch(target):
                raise ValueError('reviewed Bluesky destination differs from configured handle')
            sess = self._session(handle, app_pw)
            did, jwt = sess.get("did"), sess.get("accessJwt")
            if (not all(isinstance(value, str) and value.strip() for value in (did, jwt))
                    or not _DID_RE.fullmatch(did) or _handle(sess.get('handle')) != handle):
                raise ValueError('Bluesky session did not prove the configured handle')
            authenticated = {'platform': self.platform, 'account': _handle(sess['handle']),
                             'repository': did, 'destination': did}
            if not matching_owned_identity(authenticated, payload):
                raise ValueError('authenticated Bluesky identity differs from reviewed account/destination')
        except Exception as exc:
            receipt = _not_applied(payload, self.platform, 'Bluesky identity preflight failed: ' + type(exc).__name__)
            if isinstance(exc, urllib.error.HTTPError) and exc.code == 429:
                receipt.update(rate_limited=True, code=429)
            return receipt
        try:
            import datetime as _dt
            record = {"repo": did, "collection": "app.bsky.feed.post",
                      "record": {"$type": "app.bsky.feed.post", "text": text,
                                 "createdAt": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")}}
            data = json.dumps(record).encode("utf-8")
            req = urllib.request.Request(f"{self.PDS}/xrpc/com.atproto.repo.createRecord",
                                         data=data, method="POST",
                                         headers={"Authorization": f"Bearer {jwt}", "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                resp = json.loads(r.read().decode("utf-8"))
            uri = resp.get('uri') if isinstance(resp, dict) else None
            match = _POST_URI_RE.fullmatch(uri) if isinstance(uri, str) else None
            repository = match.group(1) if match else None
            receipt = _owned_receipt(payload, self.platform, uri,
                                     {'account': authenticated['account'], 'repository': repository,
                                      'destination': repository})
            if repository != did:
                receipt.update(status='uncertain', reason='Bluesky post URI did not confirm the authenticated repository')
            return receipt
        except urllib.error.HTTPError as e:
            detail = (e.read().decode("utf-8", "replace") or "")[:200]
            if e.code == 429:
                return {"status": "throttled", "rate_limited": True, "reason": "bluesky 429", "detail": detail}
            return {"status": "error", "code": e.code, "reason": detail}
        except Exception as e:  # pragma: no cover (live-only network)
            return {"status": "uncertain", "reason": 'Bluesky publish response was not confirmed: ' + type(e).__name__}


class ManualPrepProvider(Provider):
    """A channel whose ONLY compliant path is a HUMAN posting (the ToS-hostile / anti-ad surfaces:
    r/SillyTavernAI's weekly megathread, organic 'what API' answers, a Chub/JanitorAI proxy-guide
    card, a ProductHunt/Show HN launch). Automated egress here would be spam and would get the
    account -- and the brand -- banned, so LIVE_TRANSPORT stays False FOREVER: publish/dm never send.

    But 'manual' must not mean 'inert': the skill still does the work a human can't, and the bandit
    still learns. Two verbs make the human a first-class actuator:
      prep(payload)         -> the finished, arm-selected copy + aff link + a compliant posting
                               checklist for THIS surface. No egress. The caller records a
                               'prepared' event (arm/propensity/policy_version) so OPE sees the draw.
      record_post(url,...)  -> the human posted; write a real 'sent' event tying that post to the arm
                               so a later conversion on register?aff attributes back and the bandit
                               updates. This is the loop-close for human-actuated channels.

    Compliance is structural: no code path here can emit to the network, so 'never auto-post to a
    ToS-hostile surface' is enforced by construction, not by a flag someone can flip."""
    LIVE_TRANSPORT = False  # permanent: a human is the actuator, never the API

    def __init__(self, platform, guidance, surface=""):
        self.platform = platform
        self.surface = surface or platform
        self.guidance = guidance  # a compliant posting checklist specific to this surface
        self.deferred_reason = ("manual-prep channel: the skill prepares copy + tracks; a HUMAN posts "
                                "(automated egress would be spam/ban). Use `prep` then `record-post`.")

    def prep(self, payload):
        """Return the finished post a human will paste, plus a compliance checklist. No egress."""
        parts = [p for p in (payload.get("subject"), (payload.get("body") or "").strip(),
                             (payload.get("cta") or "").strip()) if p]
        return {
            "status": "prepared",
            "platform": self.platform,
            "surface": self.surface,
            "copy": "\n\n".join(parts),
            "cta": payload.get("cta"),
            "checklist": self.guidance,
            "reminder": "Post this by hand on %s, then run: promotion-assistant record-post "
                        "--channel <slug> --url <permalink>" % self.surface,
        }


class _DeferredPlatform(Provider):
    def __init__(self, platform, reason):
        self.platform = platform
        self.deferred_reason = reason
        self.LIVE_TRANSPORT = False


# Registry of demand-side channel primitives. Channels WITHOUT a compliant automated transport
# are registered anyway (coverage floor) and surfaced as explicit deferred-gaps.
def build_registry():
    return {
        "email": EmailProvider(),
        "discord": DiscordOwnServerProvider(),
        # AUTOMATED (owned-account self-timeline REST): compliant self-broadcast. Still gated by
        # dispatch.py's two switches + throttle; needs owned-account creds in env to actually send.
        "mastodon": MastodonProvider(),
        "bluesky": BlueskyProvider(),
        # DEFERRED: X free tier (~17/day) is unusable and paid isn't justified until owned surfaces
        # saturate (per the 2026-07 research). Stays an explicit gap.
        "x": _DeferredPlatform("x", "X API free tier unusable (~17/day); Basic/paid deferred"),
        # MANUAL-PREP: a human must post (ToS-hostile / anti-ad surfaces). The skill preps + tracks;
        # automated egress here would be spam/ban, so LIVE_TRANSPORT is permanently False.
        "reddit": ManualPrepProvider(
            "reddit", surface="the r/SillyTavernAI weekly Models/APIs megathread",
            guidance=[
                "ONLY post in the designated weekly megathread or as an organic answer to a 'what API' "
                "question -- NEVER a top-level ad post (that is spam and gets removed/banned).",
                "Post from an AGED account with real karma; a fresh account is shadowbanned on sight.",
                "Lead with genuine help; the aff link is secondary, never the whole comment.",
                "Do not repost the same copy across subs; respect each sub's self-promo rule (often 9:1).",
            ]),
        "janitorai-card": ManualPrepProvider(
            "janitorai-card", surface="a Chub / JanitorAI proxy-guide character card or setup post",
            guidance=[
                "Publish as YOUR OWN content (a SFW proxy-guide card / setup guide) -- your content, no "
                "platform ToS issue.",
                "Honest instructions only. NO 'unlimited free' / 'no limits' claims (banned_claims).",
                "Every link carries register?aff=<code>. Keep it a genuine how-to, not an ad.",
            ]),
        "producthunt": ManualPrepProvider(
            "producthunt", surface="a ProductHunt launch (Tue/Wed/Thu, 12:01 PST)",
            guidance=[
                "Manual human launch only. NEVER solicit or ring votes -- that is ToS violation + delisting.",
                "The skill preps the assets/copy and tracks the outcome; a human runs the launch.",
            ]),
        "hackernews": ManualPrepProvider(
            "hackernews", surface="a Show HN post",
            guidance=[
                "Show HN, manual, with a gateless working demo. NEVER vote-ring or use sockpuppets.",
                "Honest, technical framing for the indie-dev ICP; the skill preps + tracks only.",
            ]),
    }


def get(platform):
    return build_registry().get(platform, _DeferredPlatform(platform, "unknown platform"))
