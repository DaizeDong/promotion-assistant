# Caller migration

Calls use one llmcall request with inherited model, effort and routing defaults.
Explicit user selections remain constraints. Timeouts, uncertain effects and
invalid outputs never cause a second business model call. Synthetic tests do
not certify production capabilities.

Draft assistance requires read-only access with no tools or tool network.
Failed and empty results return nonzero before recording a draft event.
Compliance checks and human-only publication remain.
