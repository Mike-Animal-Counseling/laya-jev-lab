# Self-hosted workspaces

Deploy `service.server` for remote teams. It provides login, isolated workspaces, owner/member/viewer roles, scoped keys and Zendesk sync. The local evaluation `backend/server.py` remains single-user and loopback-only.

## Docker

Use Compose v2 on Linux amd64. HTTPS override requires Compose 2.24.4+ for `!reset`. Start with 4 GB available memory and at least 5 GB disk space; builds and existing Docker caches may need substantially more. Monitor actual workload. The CPU archive is about 600 MB.

Download [laya-v5-inference.zip](https://github.com/Mike-Animal-Counseling/laya-jev-lab/releases/download/v0.1.0/laya-v5-inference.zip) to `downloads/`. SHA256: `3be56e2273a9c1b1c7cb59ea42e4c2926ef0c3a86ea1c0ef6cee050d8270e12b`. The unchanged V5 asset works with v0.2.0; its manifest and notices remain identical. Import verifies every declared file. Weights are separate from source/images.

```sh
docker compose build
docker compose run --rm api python -m service.manage init --workspace demo --owner admin
docker compose --profile setup run --rm model-install
docker compose up -d --wait
```

Choose your own password when prompted; no default account exists. Open **http://127.0.0.1:5180/laya-ft**, workspace `demo`, username `admin`. Workspaces start empty. First model load can take a minute. Jev-only deployments can skip model installation.

Named volumes `workspace-data` and `model-data` survive replacement. Import refuses overwrites. Do not use `docker compose down -v` on data you need.

## HTTPS

Point your DNS name at the server and open 80/443. Bash:

```sh
export SERVICE_PUBLIC_URL=https://tickets.example.com
export SERVICE_DOMAIN=tickets.example.com
docker compose -f compose.yml -f deploy/compose.https.yml up -d --wait
```

PowerShell uses `$env:SERVICE_PUBLIC_URL='https://tickets.example.com'` and `$env:SERVICE_DOMAIN='tickets.example.com'`. Preserve this public configuration across upgrades. Caddy obtains certificates and removes the web host port; the API has no published port.

An alternative proxy must preserve Host, forward same-origin `/api` and `/v1`, require HTTPS, and avoid logging sensitive queries/payloads. Set one exact public origin. Remote HTTP is rejected; browser writes require matching Origin and CSRF. Run **one API replica**: SQLite jobs and rotating credentials do not support multi-replica/high-availability operation. Pin a reviewed Git commit for upgrades.

## Accounts

Create other isolated workspaces with the same operator command and different slugs. No public registration is exposed. Owners invite users through **Settings → Team**. One-use links expire after 24 hours and carry their token in a URL fragment.

| Role | Access |
| --- | --- |
| Owner | Tickets, connections, people, keys, sync, archive |
| Member | Import, analyze, assign, review, complete, export |
| Viewer | Read tickets, saved comparison, export |

Disable members to revoke sessions. Owner disabling is blocked. Recover passwords with:

```sh
docker compose exec api python -m service.manage reset-password --workspace demo --username admin
```

This prompts for a new password and revokes sessions. Sessions expire after eight hours. Workspace limits: 100 accounts/pending invitations, 100 active keys, 1,000 inbox tickets. Enterprise SSO, billing and public SaaS provisioning are not included.

## Zendesk

1. Register your own OAuth client with callback `https://tickets.example.com/api/oauth/zendesk/callback` using the real origin. A public PKCE client can leave the secret blank; otherwise supply the configured client secret.
2. Save subdomain/client identifier/optional secret in **Settings → Connections**, then **Connect**. Authorize ticket read access. Incremental exports require an administrator.
3. Run or enable **Settings → Sync**. The first window starts one hour before workspace creation.

PKCE S256 and one-use session-bound state protect authorization. Expiring tokens and rotating refresh tokens are encrypted. Disconnect pauses sync, removes local tokens and attempts provider revocation. If revocation fails, revoke in Zendesk too.

Cursor exports read 100 tickets/page. Catch-up pages are at least a minute apart; normal polling uses your chosen interval. Source updates clear stale analyses. Tickets and cursor commit atomically. Errors back off and retain the cursor; pause cancels in-flight commits. Sync never invokes AI or modifies Zendesk tickets.

Invalid/oversized source tickets or capacity limits stop that page without dropping records. Correct source data or export/archive records before resuming. Before the first cursor, an owner may set an earlier `start_time` through same-origin `POST /api/sync/configure` with `{"enabled":true,"interval":600,"start_time":UNIX_SECONDS}` and browser CSRF. Historical start time is not yet exposed in settings. Long migrations take multiple pages.

References: [OAuth migration](https://developer.zendesk.com/documentation/authentication/oauth-migration/), [incremental exports](https://developer.zendesk.com/api-reference/ticketing/ticket-management/incremental_exports/), [global clients](https://developer.zendesk.com/documentation/marketplace/building-a-marketplace-app/set-up-a-global-oauth-client/). A distributed OAuth app for unrelated customers can require a global client approval. Domain/client registration and real-account authorization are operator setup; no creator app/key is bundled.

REST/IMAP provide bounded manual preview/import. Mailbox OAuth and scheduled REST/IMAP remain extensions behind the [intake contract](../INTAKE.md).

## Backup and operation

```sh
docker compose exec api python -m service.manage backup /app/var/cloud/backups/snapshot.sqlite3
docker compose cp api:/app/var/cloud/backups/snapshot.sqlite3 ./private-backup.sqlite3
docker compose cp api:/app/var/cloud/master.key ./private-master.key
```

Choose a fresh filename. Protect snapshot and key separately; both recover encrypted settings. Ticket text is not encrypted by the application. Use encrypted disks/backups, restrict operator access and never publish these files.

Test restoration in an isolated volume: stop API, restore snapshot as `service.sqlite3` and matching `master.key`, remove obsolete WAL/SHM only from that stopped restored store, preserve UID 10001 ownership, restart one replica. Verify login/model/settings before sync.

Back up before reviewing an update and running `docker compose up -d --build --wait`. Volumes remain. The current schema creates missing tables; review future breaking migrations. Monitor health, disk, resources and sync; add edge quotas. Build cache can accumulate independently of application data: inspect `docker system df` before rebuilding. `docker builder prune` removes unused build cache, not volumes; on Windows/WSL the virtual disk may need separate space reclamation. Never substitute a volume deletion for cache cleanup.

Owners remove live inbox records through `POST /api/tickets/archive` with `{"ids":["TK-1041"],"confirm":true}` after export. This does not erase caches, backups or source records; sources may re-import them. Completed/failed API results retain at least seven days, audits retain the latest 5,000 metadata events. Establish your own retention/deletion policy.
