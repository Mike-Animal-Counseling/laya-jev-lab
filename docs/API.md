# Helpdesk integration API

Run the [authenticated service](DEPLOYMENT.md), create a key in **Settings → API**, and send `Authorization: Bearer YOUR_INTEGRATION_KEY`. Keep the key in your backend. Browser sessions do not grant REST access. Workspace identity comes from the key, never a caller-supplied tenant ID.

| Route | Scope | Behavior |
| --- | --- | --- |
| `POST /v1/classify` | `classify` | Classify title/body without creating an inbox ticket |
| `POST /v1/compare` | `classify` | Explicitly run Laya followed by Jev |
| `POST /v1/tickets` | `tickets:write` | Atomic import/upsert of 1–100 source tickets |
| `GET /v1/tickets?offset=0&limit=100` | `tickets:read` | Read workspace tickets |
| `GET /v1/tickets/{id}` | `tickets:read` | Read a ticket and engine-specific results |
| `POST /v1/tickets/{id}/classify` | `classify`, `tickets:write` | Analyze and save with revision checking |
| `GET /v1/requests/{UUID}` | `tickets:read` | Read request status and cached result |
| `GET /v1/openapi.json` | Public | Machine-readable contract |

Keys expire after 90 days by default and can be revoked.

## Stateless classification

```json
{"engine":"laya","subject":"Duplicate charge","message":"Please refund the extra payment."}
```

POST to `/v1/classify` with `Content-Type: application/json` and a fresh UUID in `Idempotency-Key`. Choose `laya` or `jev`. The response contains `request_id` and `result`, using the [SDK fields](../INTEGRATION.md). The request table retains the result and input digest without original title/body. Inbox imports do retain their content.

```python
from uuid import uuid4
from ticket_engine import ServiceClient

client = ServiceClient("https://tickets.example.com", api_key=integration_key)
response = client.classify("Please refund the duplicate payment.",
                           subject="Billing", engine="laya", request_id=str(uuid4()))
print(response["result"])
```

Your adapter maps categories to queues and handles `needs_review`. This service does not write back to Zendesk. Comparison can incur Jev charges even if the overall operation fails.

## Import and update

```json
{"tickets":[{"subject":"Duplicate charge","message":"Please refund the extra payment.",
              "source":"api","source_id":"helpdesk:example-01"}],"update":true}
```

`source` plus `source_id` is a workspace-scoped identity. Without it, exact content detects duplicates. `update: true` updates matching tickets; changed title/body invalidates both analyses and saved reference labels. Unknown identities create tickets. The response returns imported/updated/skipped counts and inbox IDs. Import never invokes AI.

Read `runs["laya-ft"].revision` or `runs["jev"].revision`, then POST `{"engine":"laya","expected_revision":0}` to `/v1/tickets/TK-1041/classify` with a fresh UUID. Changed revisions return 409; refresh before a new logical operation. IDs are not recycled after archive.

## Retries and limits

Persist a UUID with each logical operation. Identical completed retries return cached results. Different input using the same UUID returns 409. `pending` can mean an uncertain outcome after process failure: check status and reconcile rather than repeating paid calls automatically. Failed requests retain their safe error; a deliberate new operation after resolving its cause needs a new UUID. `ServiceClient` performs no automatic retries and exposes `request_status()`.

Completed/failed records are pruned on later writes after seven days; protection is not indefinite. Pending records remain for manual reconciliation. Each workspace holds at most 10,000 retained request records.

Subjects: 120 characters. Bodies: 3,000. Imports: 100 rows/2 MB per call. Other JSON requests: 24 KB. Inbox: 1,000 active tickets. API traffic: 120 requests/minute/workspace; stateless classification: 30/minute. Add edge quotas for public deployments.

Configure Jev per workspace or install pinned Laya files before classification. Missing configuration fails explicitly; there is no engine fallback.
