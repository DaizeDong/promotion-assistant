#!/usr/bin/env python3
"""Read-only Reddit access for the participation copilot. READ ONLY -- this file never writes,
votes, or posts. Two compliant paths, no scraping/evasion:

  1. Official OAuth (preferred): a Reddit "script" app you register (client_id/secret in a
     gitignored env), authenticated as YOUR account, hitting documented read endpoints within
     documented rate limits. This is the sanctioned developer path (as automation-rube uses via
     Composio) -- not a bypass.
  2. Web-search fallback: build `site:reddit.com` queries (the opportunity-research pattern) for
     the operator's existing search tooling (tavily / brightdata MCP) to run. Anonymous
     www.reddit.com/*.json is 403 for datacenter IPs since 2023, so we do NOT hammer it; the
     fallback goes through a real search engine instead.

The module stays pure + testable: it builds queries and PARSES results, but the actual network
call is injected by the CLI/agent (fetch_json callable for OAuth, or search results for fallback).
Nothing here holds a socket open on import.
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

# ------------------------------------------------------------------------------------------------
# Query construction (opportunity-research's three-bucket site:reddit.com taxonomy)
# ------------------------------------------------------------------------------------------------

def build_search_queries(pain_points, category, competitors=None, subreddit=None) -> list:
    """Build a set of site:reddit.com search queries to surface threads where genuine help fits.
    Three buckets: problem, solution, competitor. Optionally scoped to one subreddit."""
    competitors = competitors or []
    scope = (" %s" % ("subreddit:" + subreddit)) if subreddit else ""
    site = "site:reddit.com"
    qs = []
    for p in pain_points:
        qs += [f"{site} {p}{scope}", f"{site} {p} help{scope}", f"{site} {p} recommendation{scope}"]
    qs += [f"{site} best {category}{scope}", f"{site} how to {category}{scope}"]
    for c in competitors:
        qs += [f"{site} {c} alternative{scope}", f"{site} {c} review{scope}",
               f"{site} {category} vs {c}{scope}"]
    # de-dup, cap at 40 (opportunity-research "start with 20-40 searches")
    seen, out = set(), []
    for q in qs:
        if q not in seen:
            seen.add(q); out.append(q)
        if len(out) >= 40:
            break
    return out


# ------------------------------------------------------------------------------------------------
# OAuth (official, read-only). Credentials from a gitignored env file; never committed, never echoed.
# ------------------------------------------------------------------------------------------------

def load_reddit_creds(secrets_path: Path) -> dict:
    """Read client_id / client_secret / username / password / user_agent from a gitignored env.
    Returns {} if not present (caller degrades to web-search fallback). Never prints secrets."""
    if not secrets_path.is_file():
        return {}
    creds = {}
    for line in secrets_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        creds[k.strip()] = v.strip()
    need = ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "REDDIT_USERNAME",
            "REDDIT_PASSWORD", "REDDIT_USER_AGENT")
    if all(creds.get(k) for k in need):
        return creds
    return {}


def get_oauth_token(creds: dict, *, urlopen=urllib.request.urlopen):
    """Fetch a read-only OAuth token via the official password grant for a script app.
    urlopen injectable for tests. Returns (token, error)."""
    try:
        import base64
        auth = base64.b64encode(
            ("%s:%s" % (creds["REDDIT_CLIENT_ID"], creds["REDDIT_CLIENT_SECRET"])).encode()
        ).decode()
        data = urllib.parse.urlencode({
            "grant_type": "password",
            "username": creds["REDDIT_USERNAME"],
            "password": creds["REDDIT_PASSWORD"],
        }).encode()
        req = urllib.request.Request(
            "https://www.reddit.com/api/v1/access_token", data=data, method="POST",
            headers={"Authorization": "Basic " + auth,
                     "User-Agent": creds["REDDIT_USER_AGENT"],
                     "Content-Type": "application/x-www-form-urlencoded"})
        with urlopen(req, timeout=30) as r:
            body = json.loads(r.read().decode("utf-8"))
        tok = body.get("access_token")
        return (tok, None) if tok else (None, "no access_token in response")
    except Exception as e:  # pragma: no cover (network)
        return (None, str(e)[:200])


def fetch_new(subreddit: str, token: str, user_agent: str, *, limit=25,
              urlopen=urllib.request.urlopen):
    """Fetch newest posts from a subreddit via the OAuth read endpoint. Returns (posts, error).
    READ ONLY. posts normalized to the schema participation.score_opportunity expects."""
    try:
        url = "https://oauth.reddit.com/r/%s/new?limit=%d" % (
            urllib.parse.quote(subreddit), int(limit))
        req = urllib.request.Request(url, headers={
            "Authorization": "Bearer " + token, "User-Agent": user_agent})
        with urlopen(req, timeout=30) as r:
            body = json.loads(r.read().decode("utf-8"))
        return (parse_listing(body), None)
    except Exception as e:  # pragma: no cover (network)
        return ([], str(e)[:200])


def parse_listing(body: dict) -> list:
    """Normalize a Reddit listing JSON into the participation post schema. Pure."""
    out = []
    for child in (body.get("data", {}) or {}).get("children", []) or []:
        d = child.get("data", {}) or {}
        out.append({
            "id": d.get("id"),
            "fullname": d.get("name"),  # t3_xxx stable handle (audit trail)
            "title": d.get("title", "") or "",
            "body": d.get("selftext", "") or "",
            "subreddit": d.get("subreddit", ""),
            "num_comments": d.get("num_comments"),
            "score": d.get("score"),
            "created_utc": d.get("created_utc"),
            "permalink": ("https://www.reddit.com" + d.get("permalink", "")) if d.get("permalink") else None,
            "link_flair": d.get("link_flair_text"),
        })
    return out
