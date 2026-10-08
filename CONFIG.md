# promotion-assistant, Config

`promotion-assistant` is **config-bearing**. The skill itself is product-agnostic: all product copy,
audiences, per-channel policy, runtime metrics and credentials live in a **separate, private
companion config repo**. This file is the authoritative config contract (config-spec E1);
the in-engine field reference is [`skills/promotion-assistant/reference/config-schema.md`](skills/promotion-assistant/reference/config-schema.md).

## Discovery convention (how the skill finds your config), E2

An explicit `--config` path is authoritative. Otherwise `scripts/config.py` uses the highest
nonempty environment selection below. A missing or malformed selection fails without falling
through to another product. Home locations apply only when no environment selection exists:

1. `$PROMO_CONFIG_DIR`, **primary**, recommended (the canonical name this skill uses).
2. `$PROMOTION_ASSISTANT_CONFIG`, config-spec canonical alias (accepted).
3. `$PROMOTION_ASSISTANT_CONFIG_DIR`, config-spec canonical alias (accepted).
4. `~/.promotion-assistant-config/`, dotfile-in-home fallback.
5. `~/.config/promotion-assistant-config/`, XDG-style fallback (Linux/macOS).

If none resolves, the engine fails closed with a clear message (it never invents a default product).
The selected directory must belong to a separate versioned PRIVATE Git companion. Git resolves
ordinary and linked worktrees. Every effective fetch and push URL on every remote must resolve
to the matching PRIVATE GitHub identity. Each operation obtains a new proof through the pinned
Guards API, using the local `~/.pii-guard/visibility.json` receipt and both physical and effective
Git configuration. Missing, stale, malformed or unknown evidence fails; storage operations do not
make network visibility queries or refresh receipts. See the [shared contract](guards/COMPANION.md#verifying-a-companion).
PUBLIC, unknown, unversioned, source-tree, escaping canonical DATA paths and hardlinked runtime
files fail before use. `doctor` names the accepted PRIVATE publication identities.
Local absolute helper/interpreter paths are resources and need not be inside the companion.

## Schema (E1)

```
<product>-promo-config/
  product.json                  # profile + the GLOBAL send gate
  registry.json                 # one row per channel
  channels/<slug>/policy.json   # throttle policy (hot-swappable; never hardcoded in the skill)
  copy/<campaign>.json|.yaml    # campaign arms
  audiences.json|.yaml          # segment definitions
  compliance/consent-ledger.jsonl   # versioned PRIVATE lawful-basis records
  metrics/                      # versioned PRIVATE events, previews, bandit/throttle state and suppression
  metrics/runs/<run-id>.json     # versioned PRIVATE frozen intent and per-item receipts
  secrets/runtime.env           # selected-root runtime resource mapping; private only
  runbooks/                     # new-machine.md, live-authorize.md, ban-recovery.md
```

**`product.json`**

| field | type | required | notes |
|---|---|---|---|
| `schema_version` | int | yes | config contract version (init stamps `1`); lets the engine migrate older configs |
| `name` | str | yes | product name |
| `send_mode` | enum `dry_run`\|`live` | no (default `dry_run`) | **global send gate**; live also needs `PROMO_LIVE_AUTHORIZED_<CHANNEL>` |
| `aff_base` | str | no | conversion anchor; per-channel ref = channel attribution |
| `banned_claims` | list[str] | no | compliance lint blocklist |
| `compliance.physical_address` | str | no (recommended) | CAN-SPAM footer |
| `compliance.unsubscribe_url` | str | no (recommended) | CAN-SPAM footer |

**`registry.json`** carries its own `schema_version` (int, **required**; init stamps `1`) alongside
**`channels[]`** (each row): `slug` (str, **required**), `platform` (str),
`transport` (str), `account_handle` (str), `warmup_state` (str), `live_authorize_token` (str,
optional, when set, the live second factor is strengthened to a constant-time equality check).

**`channels/<slug>/policy.json`**: `day`/`hour`/`week` caps, `min`/`max` gap, `warmup_curve`,
`backoff` (AIMD). Hot-swappable, loaded at runtime, never baked into the skill.

**`copy`/`audiences`** load as `.json`; `.yaml` is accepted when PyYAML is installed, otherwise the
loader falls back to a `.json` sibling (zero hard third-party deps).

## First-time setup (E3)

```bash
cd skills/promotion-assistant

# 1. Stamp a conformant, empty config skeleton (deterministic — E4):
python scripts/init_config.py             # -> ~/.promotion-assistant-config/  (or pass --out <dir>)

# 2. Point the skill at it (skip if you used the default path):
export PROMO_CONFIG_DIR=~/.promotion-assistant-config

# 3. Use a separate Git companion with a committed HEAD and PRIVATE fetch/push destinations on every remote.
# 4. Fill product.json + registry.json + channels/<slug>/policy.json and secrets/runtime.env;
#    commit the PRIVATE companion and confirm local readiness:
python scripts/verify_config.py           # doctor: PASS/FAIL per check, names what is missing
```

`init_config.py` is template-driven and deterministic, re-running it (same `--out`) produces a
byte-identical skeleton, so two operators generate the same structure (E4). It intentionally does
**not** generate or require a companion `apply.py`. The source reads `secrets/runtime.env`
for each selected configuration; source `apply` performs doctor validation without global mutation.

## Switching between configs (hot-swap), E5

A selected root owns product data and `secrets/runtime.env`. Clear stale higher-priority selectors,
select the new root and rerun doctor. Credential binding changes with that root. Live authorization
remains process-local and must be reviewed for the selected product:

```bash
export PROMO_CONFIG_DIR=~/configs/product-a     # config A
export PROMO_CONFIG_DIR=~/configs/product-b     # config B — same skill, different product
```

Verify a swap: `python scripts/init_config.py --out ~/configs/product-a` and `--out ~/configs/product-b`,
run `python scripts/verify_config.py --config-dir <each>`, then flip `$PROMO_CONFIG_DIR`, both must
report READY after their PRIVATE origins and required channel resources are configured.

## Review, delivery and recovery

Addressed channels select `audiences.segments[arm.segment]`, with `recipient` and ISO country
`recipient_country` on every row. Suppression and duplicate lookup use a separate normalized key;
the selected recipient's case and tag are preserved for transport. Equivalent aliases collapse to
the first selected address; conflicting non-address metadata blocks.
Owned broadcasts declare registry `audience_mode: "owned_broadcast"` and an explicit `destination`.
They review one destination and do not require an email audience segment. Requested `--channel`
scope applies to both `run` and `prep`.

For Mastodon and Bluesky, the run freezes `account_handle` as well as `destination` and carries
both to the provider. Mastodon requires the reviewed local username or full `username@host`,
and a destination identifying that account: its HTTPS profile URL or full `username@host`.
`PROMO_MASTODON_INSTANCE` must be the HTTPS origin of that profile. Before posting, the adapter
calls `accounts/verify_credentials` and compares the token owner's ID, username, account and
profile with the reviewed intent. The post response must identify the same account and instance.

Bluesky accepts the reviewed handle or DID for `account_handle`. Its destination must be that
handle, DID, or `https://bsky.app/profile/` URL. `PROMO_BLUESKY_HANDLE` must agree with a reviewed
handle before authentication, and the session must prove the configured handle and reviewed
repository. The returned post URI must name that same repository and the post collection.
Receipts retain the observed handle, repository or Mastodon account/profile identity.

An authentication lookup does not publish content. Identity preflight failures record proof
that no publish request was made and can be retried with the same run after credentials are
corrected. Once publication is attempted, incomplete or inconsistent response identity remains
uncertain and cannot trigger an automatic duplicate retry. These checks do not add another
authorization path: both existing live switches and the compliance review must still pass.

The latest consent-ledger row wins. Explicit withdrawal always blocks, and EU/EEA recipients
require a current lawful basis. Every dispatch and resume reloads consent and suppression.
Dry logs retain the full payload and eligibility for blocked and eligible destinations.

`run --campaign C --run-id ID` exclusively creates a durable run. An existing ID requires
`--resume`. Resume uses the frozen arm, payloads and destination set, rejects scope changes, and
never expands a changed audience file. Each item is durably marked uncertain before its provider
is called. Matching sent receipts require a remote message ID and confirm completion. Missing,
mismatched or ambiguous replies remain uncertain; the default reconciler reports unknown and
does not resend. Only matching proof that an action was not applied permits retry with the same
key. A stale run lock after a hard process kill requires operator inspection before removal.

Results include `run_id`, `status`, `counts` and `items`. Uniform item status becomes the run
status; mixed results are `uncertain` if any item is uncertain, otherwise `partial`. CLI `run`
exits zero only for `complete` or `simulated`. Successful `prep` is `prepared`, separate from
delivery. Keep runtime DATA under version control in the PRIVATE companion, including dry logs.

`channels list --json` separates implementation, configuration and live proof.
`doctor --json --channel SLUG` checks selected local resources without delivery probes. It reads the selected resource file
but never prints credential values. Scheduling is complete only after the base returns successful JSON receipts
with task IDs; unavailable or failed registration makes `plan` exit nonzero.

## Private credentials (E6)

The companion config repo is **separate and private**. Direct-child `secrets/*.env` files are
core, versioned artifacts under the source storage contract; keep them in that PRIVATE
companion and restore them with its reviewed credential history. Runtime adapters read
`secrets/runtime.env`; no MCP template or companion apply script is required. Its allowed keys are
`PROMO_SEND_GMAIL`, `PROMO_DISCORD_BOT_TOKEN`, `PROMO_DISCORD_ANNOUNCE_CHANNEL_ID`,
`PROMO_DISCORD_ALLOW_EMBED`, `PROMO_MASTODON_INSTANCE`, `PROMO_MASTODON_TOKEN`,
`PROMO_BLUESKY_HANDLE` and `PROMO_BLUESKY_APP_PASSWORD`. Use UTF-8 `KEY=VALUE` lines;
blank/comment lines and matching quotes are supported, shell expansion is not. Unknown or duplicate
keys fail without echoing values. A relative email-helper path is rooted in the selected companion.
Missing bindings report not_ready for automated channels. Manual-prep channels require valid
product/registry schema and selected channel registration, but no provider credentials.
`PROMO_LIVE_AUTHORIZED_*` is deliberately not loaded from this file. The public source ignores
credential files defensively; real values belong only in approved private storage.


## Email helper setup

Email channels must declare email_helper_contract as reviewed-email-v1 after the selected helper
implements the [complete request and receipt contract](skills/promotion-assistant/reference/email-helper-contract.md).
The helper receives the exact recipient, sender, subject, body, CTA, postal address and unsubscribe
content as one frozen JSON request. Unsupported setup returns matching not_applied evidence before
publication. Incomplete or inconsistent receipts after helper invocation remain uncertain.

## Shared admission and observation accounting

Production dispatch reserves capacity in the companion's shared throttle state before any provider
effect. Reservation identity binds the account, platform, action and full frozen payload. Reusing an
identity with different intent fails. A safe retry can reuse its same-period reservation, but current
pacing and cooldown still apply; an old-period reservation cannot bypass a new daily cap. Malformed
existing state stops admission. A 429 persists account cooldown before the next item, while the
affected item's publication outcome remains uncertain. Failure to persist cooldown stops the run.

Bandit posterior updates and credited observation receipts commit together. Only stable event IDs
linked to the saved run's decisions are considered; unchanged completed resumes do not train again.
New delayed observations can update once. A legacy posterior without credit receipts baselines the
currently visible observations without changing its posterior, avoiding historical double credit.
Censored observations require a new linked event before reevaluation; time passing on a status-only
resume does not invent a negative outcome. Discounting occurs when a new decision group is credited.

Manual prep validates the complete generated copy before recording a prepared decision.
record-post --arm-id records an explicit human choice without a fabricated propensity; using
--decision-id links the actual prepared stochastic choice. Human choices are not suitable input for
stochastic off-policy estimation. participate record requires the source --thread and final
--type give|ask, with --draft-id when a generated draft was used. Only confirmed sent human
contributions count toward readiness. Drafts and unclassified legacy rows do not count, and repeated
permalinks cannot add another contribution or silently change its classification.

plan --days is a positive horizon for the campaign's existing slots, not a repetition count.
Its stable identity includes product, campaign, arm, channel, account, action and occurrence date.
The schedule helper must return the documented JSON receipts with task IDs; the bridge does not
pass a --json flag. Setup must verify `creation-preflight` and `ensure` in the installed helper.
The first plan records complete requests in the PRIVATE companion's `metrics/schedule-requests/`.
Retries keep the saved due time and fields even as the clock advances, including completed tasks.
Changed content or malformed saved requests stop for review; intentional date changes use the
base's update or snooze operation on the existing task.


## Runtime quota changes

The current `day_cap` is a hard admission ceiling, including retries. Lowering it preserves the current period and its consumed quota. Setting it to zero disables admission immediately. Raising it does not add tokens before the next normal refill.

AIMD capacity remains separate from that ceiling. Refill uses the lower of the learned capacity and the current policy limit. Legacy buckets without consumption metadata cannot recover exact usage from clipped AIMD tokens; they keep their period and learned capacity, but wait for normal refill before admitting another request.

Schedule requests persist as `metrics/schedule-requests/<64-hex-digest>.json` with title, due_at, idempotency_key, ext and description. Restore exact receipts with scheduler registrations before retrying. Their adjacent `.<digest>.json-<suffix>` staging and lock files are source-declared; interrupted files stay until transaction and registration outcomes are known.
