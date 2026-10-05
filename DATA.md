# Private campaign data

[storage.contract.json](storage.contract.json) declares companion storage and
retention. [CONFIG.md](CONFIG.md), the configuration loader, compliance checks and
run validators remain authoritative for content.

Keep the current product, channel registry, per-channel policies, selected campaign
arms and audience definitions. Addressed dispatch requires
`audiences.segments[arm.segment]` to contain recipient and country fields.
Planning descriptions alone do not meet that contract; migration must not invent
recipient lists or enable a live send gate.

Consent and suppression govern every dispatch and resume. Preserve applicable
withdrawals and exclusions while contact activity or compliance obligations remain.
`metrics/runs/<id>.json` freezes intent and per-item outcomes. Retain unresolved
runs and records referenced by delayed observations, idempotency checks or required
delivery evidence. A completed status alone does not prove those dependencies ended.

`metrics/events.jsonl`, `bandit-state.json` and `throttle-state.json` form the
current observation, learning and admission state. Preserve credited event identities,
reservations and cooldowns. Do not reset these to reduce disk use. Dry-run logs are
rebuildable after their specific review or diagnosis ends; retain any exact payload
that is selected evidence or still referenced.

Current credential files belong only in approved private storage and need an explicit
backup or reauthorization route. Initializer templates and copied runbooks are
rebuildable setup references. The source owns the current operating instructions;
a companion needs only a short README linking here. Legacy MCP bridge scripts with
no matching channel templates do not provision current adapters.

Use skill-smith's shared `storage_contract.py` for contract validation and metadata
inspection of a verified PRIVATE companion. It does not execute domain schemas.
Before a reviewed removal, prove the writer has stopped and resolve uncertain
delivery or commit outcomes. Generic cleanup must preserve lock files. Retention
ends by dependency and purpose, and local removal does not erase Git history.
