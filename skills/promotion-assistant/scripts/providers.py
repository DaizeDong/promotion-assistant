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

# Local infra contracts (reused, not reimplemented).
SEND_GMAIL_PS1 = Path.home() / ".local" / "send-gmail.ps1"
DISCORD_RELAY = Path.home() / ".local" / "notifier.py"

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
        "mastodon": _DeferredPlatform("mastodon", "Mastodon REST app token not configured (free, deferred)"),
        "bluesky": _DeferredPlatform("bluesky", "Bluesky app-password API not configured (free, deferred)"),
        "reddit": _DeferredPlatform("reddit", "Reddit OAuth posting per-subreddit not configured (deferred)"),
        "x": _DeferredPlatform("x", "X API free tier unusable (~17/day); Basic/paid deferred"),
        "janitorai-card": _DeferredPlatform("janitorai-card", "character-card proxy-guide is manual publish (deferred)"),
        "producthunt": _DeferredPlatform("producthunt", "PH launch is a manual human event (prep-only)"),
        "hackernews": _DeferredPlatform("hackernews", "Show HN is manual, no vote/post automation (prep-only)"),
    }


def get(platform):
    return build_registry().get(platform, _DeferredPlatform(platform, "unknown platform"))
