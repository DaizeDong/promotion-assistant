# Going live on a channel (irreversible outreach)

1. Set `product.json.send_mode = "live"`.
2. `export PROMO_LIVE_AUTHORIZED_<CHANNEL>=<any-non-empty-token>`.
3. Ensure that channel's secrets are applied (`promotion-assistant apply`).
Until BOTH are present, dispatch simulates and writes metrics/dry-run.jsonl (zero egress).
