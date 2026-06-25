# Design Brief — promotion-assistant

> Produced by skill-smith Step 0 (research-first). The design rationale, auditable.
> Full architecture: `CodesResearch/_skill-builds/07-promotion-assistant/ARCHITECTURE.md` (8-route recon).

## Best references (match-or-beat)
- Buffer/Typefully/Postiz (scheduling + queue-over-cron), Smartlead/Instantly/Lemlist (email pool +
  warmup + deliverability), PhantomBuster/Expandi (activity-DNA behavioral baseline, not raw volume).

## Frontier ideas incorporated
- Discounted/non-stationary Thompson Sampling (content fatigue / platform drift).
- Ref-system-first attribution (per-channel `register?aff=` = zero-instrumentation channel signups).
- Strong-negative reward (ban/spam/unsub) so the optimizer internalizes compliance (anti-Goodhart).
- Shadow subdomain + mailbox pool for sender-reputation isolation.

## Anti-patterns avoided
- Random delay treated as safety; fixed action sequences / same copy across accounts; bandit that
  optimizes only engagement; hardcoding platform limits; designing around X's unusable free tier;
  Discord selfbot / stranger auto-DM.

## Proof bar (tested-real)
- `selftest.py` E1-E12 (all passing): metrics exactness, bandit convergence + drift recovery,
  throttle limits, compliance fail-closure, attribution, dry-run zero-egress, propensity, schema,
  anti-fingerprint, delayed-conversion censoring, idempotency.

## Scope & focus (one job, ≤3 modules)
Blast (覆盖式) · Precision (精准式) · Metrics loop (指标闭环). Scheduling/notify/SMTP are delegated bases.
