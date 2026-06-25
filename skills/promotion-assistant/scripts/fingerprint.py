#!/usr/bin/env python3
"""Anti-fingerprint: spintax expansion + content hash + similarity guard.

Multi-account same-campaign reuse of identical copy is the #1 ban cause (X/Reddit/email all flag
it). This produces per-account variants from a spintax template `{a|b|c}` + merge vars, and a
similarity check so the orchestrator can REJECT a variant set whose pairwise similarity exceeds a
threshold (default 0.7). Deterministic under a seed for the acceptance gate (E9)."""
from __future__ import annotations

import hashlib
import random
import re

_SPIN = re.compile(r"\{([^{}]*)\}")


def expand(template: str, rng: random.Random) -> str:
    def pick(m):
        return rng.choice(m.group(1).split("|"))
    s = template
    for _ in range(8):  # nested groups
        if "{" not in s:
            break
        s = _SPIN.sub(pick, s)
    return s


def variants(template: str, n: int, *, seed=0) -> list:
    rng = random.Random(seed)
    return [expand(template, rng) for _ in range(n)]


def content_hash(text: str) -> str:
    return hashlib.sha256(text.strip().lower().encode("utf-8")).hexdigest()[:16]


def _wordset(s: str):
    return set(re.findall(r"[a-z0-9]+", s.lower()))


def similarity(a: str, b: str) -> float:
    wa, wb = _wordset(a), _wordset(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / float(len(wa | wb))


def max_pairwise_similarity(texts) -> float:
    m = 0.0
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            m = max(m, similarity(texts[i], texts[j]))
    return m
