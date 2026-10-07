# Private campaign data

[storage.contract.json](storage.contract.json) declares companion storage and
retention using paths relative to the companion repository root. [CONFIG.md](CONFIG.md), the configuration loader, compliance checks and
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
a companion needs a current README linking here. The selected apply command
delegates to the exact companion `scripts/apply.py`, and current provisioning
instructions select `scripts/capture-key.ps1`; preserve these helpers while
those interfaces depend on them. A missing template directory still prevents
provisioning, so retention does not establish a working credential bridge.

The exact `scripts/verify.sh` is a retired MCP registry verifier. Current
restoration uses the source doctor and companion `apply.py --verify`. Its retired
classification does not authorize deletion. The exact legacy
`compliance/policy.json` and `compliance/consent-ledger.template.jsonl` are
protected review inputs until their unique decisions, evidence and obligations
are reconciled. Current dispatch reads product and channel policies and the
current consent ledger; retaining legacy inputs does not validate that schema or
enable dispatch. A template filename does not prove synthetic contents or
expired consent. Companion philosophy copies are rebuildable setup guidance;
the historical companion changelog is retired after its reference dependencies
end and a separate exact-file retirement is reviewed.

Use skill-smith's shared `storage_contract.py` for contract validation and metadata
inspection of a verified PRIVATE companion. It does not execute domain schemas.
Before a reviewed removal, prove the writer has stopped and resolve uncertain
delivery or commit outcomes. Generic cleanup must preserve lock files. Retention
ends by dependency and purpose, and local removal does not erase Git history.
