# secrets/ — Mode B (gitignored)

Per-channel credentials live here as `secrets/<slug>.env` and are **gitignored** (see ../.gitignore).
Promo OAuth/SMTP creds are high blast-radius and auto-revoked, so Mode B (never committed) is
mandatory — the market-intel "Mode A" rationale does not apply here.

Only `*.env.template` files and this README are committed. Back real values up out-of-band
(cloud sync / encrypted drive); restore on a new machine by copying the `*.env` files back, then
running `python scripts/verify_config.py` from the skill repo. Files MUST be UTF-8 without BOM.
