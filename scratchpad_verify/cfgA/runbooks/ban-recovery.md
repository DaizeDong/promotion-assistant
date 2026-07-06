# Ban / throttle recovery

1. Pause the channel (remove it from registry.json or set warmup_state to a cold tier).
2. Inspect metrics/throttle-state.json and channels/<slug>/policy.json backoff (AIMD).
3. Re-warm via the warmup_curve before re-enabling live.
