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
a companion needs a current README linking here. Current source loads `secrets/runtime.env`
from the selected root; source apply validates it without running companion code. The legacy
`scripts/apply.py` may retire only after external provisioning and recovery references migrate.
Credential capture helpers remain until their actual recovery dependencies end.

The exact `scripts/verify.sh` is a retired MCP registry verifier. Current
restoration uses the source doctor against the selected root and its restored runtime.env. Its retired
classification does not authorize deletion. The exact legacy
`compliance/policy.json` and `compliance/consent-ledger.template.jsonl` are
protected review inputs until their unique decisions, evidence and obligations
are reconciled. Current dispatch reads product and channel policies and the
current consent ledger; retaining legacy inputs does not validate that schema or
enable dispatch. A template filename does not prove synthetic contents or
expired consent. Companion philosophy copies are rebuildable setup guidance;
the historical companion changelog is retired after its reference dependencies
end and a separate exact-file retirement is reviewed.

Schedule-request receipts and adjacent staging under `metrics/schedule-requests` are declared
explicitly. Keep exact request identities until plans, scheduler registrations and retries close.
Runtime writers use the pinned Guards artifact authorizer; undeclared, ignored or retired
destinations cannot receive new writes. Core locks remain versioned and protected.

Use skill-smith's shared `storage_contract.py` for contract validation and metadata
inspection of a verified PRIVATE companion. It does not execute domain schemas.
Before a reviewed removal, prove the writer has stopped and resolve uncertain
delivery or commit outcomes. Generic cleanup must preserve lock files. Retention
ends by dependency and purpose, and local removal does not erase Git history.
