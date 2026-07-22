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
OAuth posting, Mastodon REST, X API). A deferred-gap is an EXPLICIT gap, never a silent skip.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

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
    """Bulk/precision email. LIVE path = the machine's send-gmail.ps1 SMTP link (DPAPI cred,
    no secret in repo). Deliverability (SPF/DKIM/DMARC, shadow subdomain, mailbox pool, warmup,
    spintax) is config-driven; this provider only owns the send call + receipt mapping."""
    platform = "email"
    LIVE_TRANSPORT = True
    deferred_reason = "send-gmail.ps1 link present; live blast still requires per-account authorize"

    def publish(self, payload, *, live=False):
        if not live:
            return self._not_live("publish")
        if not SEND_GMAIL_PS1.is_file():
            return {"status": "error", "reason": "send-gmail.ps1 not found"}
        # ---- arg-binding hardening (live-only): validate BEFORE spawning the subprocess ----
        recipient = payload.get("recipient", "")
        subject = payload.get("subject", "")
        body = payload.get("body", "")
        if not _EMAIL_RE.match(recipient or ""):
            return {"status": "error", "reason": "invalid recipient (must be a single email address)"}
        if not _arg_binding_safe(recipient, subject, body):
            return {"status": "error",
                    "reason": "argument starts with '-' (PowerShell arg-binding guard); refused"}
        # NOTE: real invocation intentionally not auto-run in build; wired for live-authorized use.
        cmd = ["powershell", "-NoProfile", "-File", str(SEND_GMAIL_PS1),
               "-To", recipient, "-Subject", subject, "-Body", body]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=60)
            return {"status": "sent" if r.returncode == 0 else "error",
                    "rc": r.returncode, "detail": (r.stderr or "")[:200]}
        except Exception as e:  # pragma: no cover (live-only)
            return {"status": "error", "reason": str(e)[:200]}


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
        token = os.environ.get("PROMO_DISCORD_BOT_TOKEN", "").strip()
        channel_id = os.environ.get("PROMO_DISCORD_ANNOUNCE_CHANNEL_ID", "").strip()
        if not token or not channel_id:
            return {"status": "error", "platform": self.platform,
                    "reason": "PROMO_DISCORD_BOT_TOKEN / PROMO_DISCORD_ANNOUNCE_CHANNEL_ID not in env "
                              "(apply the discord-own secret before going live)"}
        if not channel_id.isdigit():
            return {"status": "error", "reason": "PROMO_DISCORD_ANNOUNCE_CHANNEL_ID must be a numeric id"}
        parts = [p for p in (
            (f"**{payload.get('subject').strip()}**" if payload.get("subject") else None),
            (payload.get("body") or "").strip() or None,
            (payload.get("cta") or "").strip() or None,
        ) if p]
        content = "\n\n".join(parts)[:1900]  # stay under Discord's 2000-char message cap
        if not content:
            return {"status": "error", "reason": "empty message (no subject/body/cta)"}
        # Suppress Discord's auto link-preview card by default: these are frequent changelog posts, and
        # a big unfurled website card on every one is noisy -- a clickable link is enough. flags=4 is
        # SUPPRESS_EMBEDS. Set PROMO_DISCORD_ALLOW_EMBED=1 for a rare launch post that wants the card.
        body = {"content": content}
        if not os.environ.get("PROMO_DISCORD_ALLOW_EMBED", "").strip():
            body["flags"] = 4
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            f"{self.API}/channels/{channel_id}/messages", data=data, method="POST",
            headers={"Authorization": f"Bot {token}", "Content-Type": "application/json",
                     "User-Agent": "promotion-assistant (https://github.com/DaizeDong/promotion-assistant, 0.1)"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                resp = json.loads(r.read().decode("utf-8"))
            return {"status": "sent", "platform": self.platform,
                    "message_id": resp.get("id"), "channel_id": channel_id}
        except urllib.error.HTTPError as e:
            detail = (e.read().decode("utf-8", "replace") or "")[:200]
            if e.code == 429:  # let the caller's AIMD throttle react to a real rate-limit
                return {"status": "throttled", "reason": "discord 429", "detail": detail}
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
        instance = os.environ.get("PROMO_MASTODON_INSTANCE", "").strip().rstrip("/")
        token = os.environ.get("PROMO_MASTODON_TOKEN", "").strip()
        if not instance or not token:
            return {"status": "error", "platform": self.platform,
                    "reason": "PROMO_MASTODON_INSTANCE / PROMO_MASTODON_TOKEN not in env"}
        parts = [p for p in ((payload.get("subject") or "").strip(), (payload.get("body") or "").strip(),
                             (payload.get("cta") or "").strip()) if p]
        status = "\n\n".join(parts)[:490]  # Mastodon default 500-char limit; leave headroom
        if not status:
            return {"status": "error", "reason": "empty status"}
        data = json.dumps({"status": status, "visibility": "public"}).encode("utf-8")
        req = urllib.request.Request(
            f"{instance}/api/v1/statuses", data=data, method="POST",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                     "Idempotency-Key": str(abs(hash(status)))[:32],
                     "User-Agent": "promotion-assistant (+https://github.com/DaizeDong/promotion-assistant)"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                resp = json.loads(r.read().decode("utf-8"))
            return {"status": "sent", "platform": self.platform,
                    "message_id": resp.get("id"), "url": resp.get("url")}
        except urllib.error.HTTPError as e:
            detail = (e.read().decode("utf-8", "replace") or "")[:200]
            if e.code == 429:
                return {"status": "throttled", "reason": "mastodon 429", "detail": detail}
            return {"status": "error", "code": e.code, "reason": detail}
        except Exception as e:  # pragma: no cover (live-only network)
            return {"status": "error", "reason": str(e)[:200]}


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
        handle = os.environ.get("PROMO_BLUESKY_HANDLE", "").strip()
        app_pw = os.environ.get("PROMO_BLUESKY_APP_PASSWORD", "").strip()
        if not handle or not app_pw:
            return {"status": "error", "platform": self.platform,
                    "reason": "PROMO_BLUESKY_HANDLE / PROMO_BLUESKY_APP_PASSWORD not in env"}
        parts = [p for p in ((payload.get("subject") or "").strip(), (payload.get("body") or "").strip(),
                             (payload.get("cta") or "").strip()) if p]
        text = "\n\n".join(parts)[:300]  # Bluesky 300-char limit
        if not text:
            return {"status": "error", "reason": "empty post"}
        try:
            sess = self._session(handle, app_pw)
            did, jwt = sess.get("did"), sess.get("accessJwt")
            if not did or not jwt:
                return {"status": "error", "reason": "bluesky session had no did/accessJwt"}
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
            return {"status": "sent", "platform": self.platform, "message_id": resp.get("uri")}
        except urllib.error.HTTPError as e:
            detail = (e.read().decode("utf-8", "replace") or "")[:200]
            if e.code == 429:
                return {"status": "throttled", "reason": "bluesky 429", "detail": detail}
            return {"status": "error", "code": e.code, "reason": detail}
        except Exception as e:  # pragma: no cover (live-only network)
            return {"status": "error", "reason": str(e)[:200]}


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
