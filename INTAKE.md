# Ticket intake

All sources produce the same ticket schema and use the same validation, duplicate checks and transactional save. Import never runs Laya or Jev. Use the local demo or the optional authenticated workspace service.

## Files

Open **Import → Excel / CSV**. Download the Excel template or use a UTF-8 CSV with a header row. Required columns: `Subject` and `Message`. Optional: `Customer`, `Company`, `Channel`. Common English aliases (`Title`, `Description`, `Body`) and Chinese headings (`标题`, `正文`, `客户`, `公司`, `渠道`) are accepted.

Limits: one Excel sheet, 100 data rows, 2 MB upload, 8 MB expanded Excel archive. Subject: 120 characters. Message: 3,000 characters. Customer/company: 100 characters. Channel: 40 characters. Unsupported formulas, macros, external links and XML entities are rejected. Correct marked rows and upload again; errors block the entire import. Exact duplicates are skipped. All new rows are saved in one transaction, with a stable request ID for safe retries.

Open **Import → Email** to upload a single `.eml` file. MIME plain text is preferred; HTML is reduced to text and is never rendered. Attachments are not imported. A Message-ID, when present, is retained as the source identity to prevent duplicate imports.

## Local demo connections

Copy `.env.example` to this repository's `.env.local` and fill only the connection you need. Never commit this file. The backend reads no parent configuration, environment credentials or system proxy. Connection status responses contain only booleans. Credentials remain in the backend and are never included in tickets or exports.

For Zendesk, set `ZENDESK_SUBDOMAIN` and preferably a scoped `ZENDESK_OAUTH_TOKEN`. Existing accounts can instead fill `ZENDESK_EMAIL` and `ZENDESK_API_TOKEN`. Authentication follows the [Zendesk documentation](https://developer.zendesk.com/api-reference/introduction/security-and-auth/). This is a local operator-owned connection; it does not implement OAuth registration or authorization for a distributed multi-customer application.

**Import → Zendesk → Sync** reads up to 100 accessible tickets from the [List Tickets endpoint](https://developer.zendesk.com/api-reference/ticketing/tickets/tickets/), ordered by most recently updated. It maps the initial description to `Message`, and displays the requester ID without making additional user-directory requests. It never writes to Zendesk. Tenant and ticket ID form a stable identity. Recorded IDs are skipped on later pulls; pagination, historical migration, source updates and write-back are future extensions.

For a generic API, fill `TICKET_API_URL` and optionally `TICKET_API_TOKEN`. **Import → API → Sync** performs one HTTPS GET with optional Bearer authentication. The response must be a JSON array or an object with a `tickets` array, with at most 100 items and a 2 MB response. Each item uses `subject`, `message`, and optional `customer`, `company`, `channel`, `id`. An ID is scoped to the configured endpoint; without an ID, exact content is used for duplicate detection.

For email, fill `MAIL_IMAP_HOST`, `MAIL_IMAP_USER`, `MAIL_IMAP_PASSWORD` and optionally `MAIL_IMAP_FOLDER` (default `INBOX`). Use the mailbox provider's supported app-password or credential mechanism. **Import → Email → Sync** uses verified TLS on port 993, selects the folder read-only, and previews the latest 20 messages. `BODY.PEEK` leaves read status unchanged. No messages are sent, deleted or moved. Each synced message needs a Message-ID. Provider-specific OAuth and scheduled synchronization can be added behind this adapter later.

All connector pulls happen only on an explicit Sync action. They use public TLS endpoints, pinned DNS results, bounded responses, connection timeouts and safe errors; redirects and private-network endpoints are not supported. Pulling produces a preview, not a saved ticket. Confirm **Import** to persist the new rows locally.

## Adapter contract

`backend/intake_sources.py` handles source-to-ticket mapping; `backend/connectors.py` handles configuration and read-only retrieval. New adapters return `(source_label, rows)`, where rows are `(row_number, normalized_ticket, issue)`. Use `normalize_row` for the shared schema. `source` and `source_id` are optional stable identities; ordinary files use exact content instead.

`POST /api/import/preview` accepts `.xlsx`, CSV or email bytes with the matching content type. `POST /api/intake/preview` accepts `{ "source": "email" | "zendesk" | "api" }`. Both return row-level `ready`, `duplicate` or `error` states. `POST /api/import` accepts `{ "rows": [...], "request_id": "UUID" }` and revalidates everything before one atomic save. All writes and previews require the app's localhost Host/Origin and CSRF controls. No general internet webhook is exposed by this loopback service.

Imported customer data stays in the local `var/` database. Preview uploads are held in memory and not stored as files. Exports can contain imported personal information. Source publishing excludes runtime data, connections and credentials.

## Shared service connections

The authenticated deployment configures each workspace in **Settings ? Connections**; it does not inherit local-demo `.env.local` or environment provider keys. Secrets are encrypted and are never read back to the browser. Zendesk uses the operator's registered OAuth client, PKCE, expiring tokens and automatic refresh. Scheduled cursor sync also updates matching source tickets and invalidates stale analyses. See [DEPLOYMENT.md](docs/DEPLOYMENT.md) for provider setup and limits.

REST and IMAP remain bounded manual previews. Confirm Import to save. The shared service requires login, an appropriate role, exact Origin and CSRF for browser actions. Imports and synchronization never invoke Laya or Jev. The generic integration API can import/upsert tickets through scoped keys; see [API.md](docs/API.md). No customer submission form is exposed.
