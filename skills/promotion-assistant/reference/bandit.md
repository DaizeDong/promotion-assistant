# L5, Decision layer (Thompson Sampling, non-stationary)

`scripts/bandit.py`, Beta-Bernoulli Thompson Sampling with optional discounting.

## Roadmap (implemented vs planned)
- **Stage 1 (shipped)**, Beta-TS: each arm `Beta(α,β)`; sample, pick argmax; reward → α+=r, β+=1-r.
  Arms start coarse (channel × a few copy variants). Verified by E2 (converges to true-best >0.9).
- **Stage 2 (shipped, REQUIRED for promotion)**, discounted TS: each round decays α/β toward the
  prior by `γ≈0.9-0.99` before sampling, so the policy never locks onto a stale optimum (content
  fatigue / platform change / seasonality). Verified by E3 (recovers from a mid-run optimum flip
  faster than stationary γ=1.0).
- **Stage 3 (planned)**, contextual CB (Vowpal Wabbit SquareCB/Bootstrap-TS): audience/time/health
  as *features not arms* to share statistical strength and beat combinatorial explosion.
- **Stage 4 (planned)**, delayed reward: `reward_partial` (immediate) + `reward_final` (back-filled
  within `conversion_window`); censoring already handled in metrics (E11).

## Off-policy + causality
Continuous optimization (find the best path) uses the bandit; a reportable "this copy is truly
better" causal claim uses fixed/sequential A/B with **always-valid p-values (mSPRT)**, never
fixed-sample A/B with peeking. Every decision logs `propensity_p` + `policy_version` so IPS/DR
off-policy estimators stay valid.

## Anti-patterns (encoded as gates)
Reward that only rewards clicks/likes and never penalizes ban/spam → learns to spam (guarded by the
strong-negative reward). Stationary bandit in a non-stationary world (guarded by discounting).
Missing propensity (guarded by E8). Independent arms under combinatorial explosion → Stage-3 context.
