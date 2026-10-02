# Reviewed email helper contract

Email is ready only after the operator installs a helper implementing this contract and sets the
channel's email_helper_contract to reviewed-email-v1. The separate installed helper has not been
verified by this source change. Unsupported helpers must remain setup failures; no compatibility
fallback invokes the legacy To/Subject/Body argument form.

The adapter invokes PowerShell with NoProfile, File and RequestJson arguments. RequestJson is one
JSON object. Values remain data within that object and must not be evaluated as commands.

| Request field | Required meaning |
|---|---|
| contract | reviewed-email-v1 |
| platform | email |
| idempotency_key | Stable saved action identity, reused only for the same frozen intent |
| destination and recipient | The exact selected recipient, including case and tag |
| sender | The reviewed From address that the transport must actually use |
| subject | The reviewed subject |
| body | Exact body, CTA, postal address and unsubscribe text, joined by two newlines |
| request_sha256 | SHA256 of the other request fields encoded as canonical JSON |

Canonical request JSON uses sorted keys, comma/colon separators, UTF-8, unescaped Unicode, and no
trailing newline. The helper must verify the digest before attempting delivery. It must either
apply the complete request or refuse it. A helper cannot silently drop a footer, change the sender
or substitute a recipient and still report sent.

On success the helper exits zero and emits one JSON object on stdout. The receipt must contain
status sent, a nonempty message_id, and observed contract, platform, idempotency_key, destination,
recipient, sender and request_sha256 fields matching the applied request. The helper must derive
sender and content evidence from what it actually submitted, not merely echo the intended values.

When the helper can establish that no publication occurred, it may exit zero with status
not_applied, the same complete identity/digest fields, and a nonempty evidence explanation.
A nonzero exit, interruption, malformed JSON, partial receipt or mismatch is uncertain. The
adapter never fills missing receipt fields from the expected request and never infers content or
sender confirmation from a message ID.

The adapter itself can return matching not_applied evidence before invoking a helper when setup,
header safety, recipient validation or frozen rendering checks fail. Those actions can be retried
with the same saved key after setup is corrected. An uncertain action requires authoritative
not-applied evidence before retry; this source does not ship a provider reconciliation lookup.

Synthetic tests exercise this protocol through a process seam. They establish local contract
behavior only and do not prove the installed helper, mailbox or delivery service.
