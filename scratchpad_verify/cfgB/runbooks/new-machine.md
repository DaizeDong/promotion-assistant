# New machine

1. `git clone <your-private-config-repo> ~/.promotion-assistant-config`
2. `export PROMO_CONFIG_DIR=~/.promotion-assistant-config` (or use the default path)
3. Copy your out-of-band `secrets/*.env` back into `secrets/`.
4. Fork `scripts/apply.py` from companion config kit; run `promotion-assistant apply`.
5. From the skill repo: `python scripts/verify_config.py` (must report READY).
