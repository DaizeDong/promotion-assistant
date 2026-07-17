# L2, Channel matrix (dual-line engine)

Every platform = one `Provider` with `publish/engage/dm/read_metrics`. Quota tables are
**hot-swappable config**; runtime response headers (`RateLimit-*`/`Retry-After`/429) win over any
table. A platform with no compliant automated transport is a registered **deferred-gap**, never a
silent skip.

## 覆盖式 blast, multi-platform posting (graded by ban-risk)
| tier | channels | automation |
|---|---|---|
| safe-auto | own Discord announce, Mastodon, Bluesky, Reddit OAuth (per-sub, slow) | official API publish allowed |
| cautious | X/Twitter | API only; free tier ~17/day ≈ unusable → Basic/paid; link in first reply; never same copy across accounts |
| human-review | LinkedIn/Instagram personal | generate→human approves→human posts (3rd-party auto = ToS breach) |
| human event | Product Hunt (Tue/Wed/Thu 12:01 PST, never solicit votes), HN Show HN (gateless demo, neutral title, never vote-ring) | skill only preps warmup list + launch-day notify + post-launch metrics |
| unique surface | JanitorAI character-card proxy-guide | templated visual guide; built-in SEO |

## 覆盖式 blast, bulk email (deliverability = infrastructure)
SPF+DKIM+DMARC mandatory; isolate sender reputation with a **shadow subdomain** (not the apex);
custom tracking domain. Mailbox **pool + rotation** (3-5 boxes, pick `sent_today<cap` & healthy).
Warmup ≥2 weeks ramp. Spintax + per-account variants for uniqueness. Opens are MPP-inflated →
optimize on **click/reply/conversion/unsub/complaint**, not opens.

## 精准式 precision, forum replies + DMs
Behavioral detection scores against the account's **own activity-DNA baseline** (relative, not
absolute), two accounts at the same volume get different outcomes. Control session density,
navigation variance, interaction texture. Random delay only changes timing, not pattern. Ramp:
2 weeks stable before raising volume; on early friction (forced logout / cookie churn / empty feed)
stop a week. **Discord/Telegram: official bot + own channels only**; selfbot/cross-server stranger
auto-DM = instant ban. IG/LinkedIn auto-DM = deferred (IG 2026: ~200/hr, 1 DM/user/24h).

The local registry (`scripts/providers.py:build_registry`) currently ships **email** and **own-server
Discord** as `LIVE_TRANSPORT` paths (both still gated behind per-channel authorize); mastodon /
bluesky / reddit / x / janitorai-card / producthunt / hackernews are registered **deferred-gaps**.
