# Security scope

This repository provides an independent ticket-classification SDK, a loopback-only evaluation workspace, and an optional authenticated self-hosted service. Deploy the service described in [DEPLOYMENT.md](docs/DEPLOYMENT.md) for shared access. Publishing its source does not grant remote access to the original author's machine, API key or database. Only the explicitly reviewed inference archive is distributed through Releases.

## Implemented controls

- Explicit source export allowlist; no history, private records or credentials in distribution.
- Repository-local model, database and configuration in the demo; the SDK accepts only caller-supplied model paths/credentials and has no database. No automatic parent workspace discovery.
- V5 inference files pinned by SHA256, safetensors weights, no arbitrary remote model code or automatic downloads.
- Archive import rejects traversal, links, duplicate names, extra files, oversized archives and overwrites.
- Loopback bindings, strict Host/Origin validation, cross-site read blocking, CSRF tokens for writes and no CORS access.
- Bounded request size, response size, connection workers, provider timeout and write frequency.
- Separate model locks, revision checks, transaction-based writes and safe error responses.
- Jev credentials only in the backend; a fixed HTTPS destination and no redirects.
- No customer text, API key or internal exception traceback in application error logs.

These controls do not defend against malware or an authorized user already running on the same computer. Anyone with access to the local files or a trusted local browser session may access that user's demo data.

## Dependency status at preparation

The source preparation removed the unnecessary `eslint-config-next` dependency chain that introduced the `braces` advisory (`GHSA-vfj7-8cjw-p6xm`). TypeScript and React Hooks lint checks remain enabled through their direct ESLint plugins. The resulting complete npm audit (including development dependencies) reported zero known vulnerabilities at preparation time.

The Python runtime uses the same directly pinned versions reviewed for this release. Advisory information changes: re-run `npm audit` and Python dependency checks before publication or deployment. A zero known-advisory count is not a proof of zero vulnerabilities.

The publication recheck on 2026-10-10 updated `sharp` to 0.35.5 and `source-map-js` to 1.2.2 for GHSA-wq5f-xc86-pv6w and GHSA-68fv-2mgg-jv7q. The complete npm audit then reported zero known vulnerabilities. The installed Python environment audit and a separate check of upstream PyTorch 2.14.0 also reported no known vulnerabilities; the upstream check was needed because the installed CPU build suffix is not indexed on PyPI.

The CI workflow checks source privacy, backend contracts, frontend interactions, lint, build, types and npm advisories including development dependencies. GitHub Actions are pinned to immutable commits and repository permissions are read-only. Tests mock providers and do not use live API keys. Dependency audits are known-advisory checks, not proof of exploit absence or a full penetration test.

## Before publication

1. Run `python scripts/check_public.py` and review the exported file list.
2. Initialize a fresh repository in this source directory, using an intended public author identity and privacy email. Do not copy another `.git` directory.
3. Enable `.githooks` and run the staged check before committing. `.gitignore` does not remove files that were already tracked.
4. Review new documentation, screenshots, attachments, issues and commit messages as public information.
5. Distribute only the reviewed inference artifact. Do not include raw datasets or training notebooks by convenience.

If a credential was ever committed or publicly shared, removing the visible file alone is insufficient: revoke/rotate the credential and address repository history. This release has not copied any prior repository history.

## Intake controls

Excel uploads have compressed and expanded size bounds, XML entity protection, fixed sheet/row/column limits, and reject macros, external links and formulas. CSV/email parsers are bounded; HTML email is converted to text and attachments are ignored. All imported rows are validated again at commit, duplicate identities are scoped to their source, and the entire batch is stored in one transaction with idempotent retry protection.

Read-only connectors use repository-local credentials, TLS verification, public DNS address validation and pinning, fixed Zendesk destinations, response limits and safe errors. API redirects, implicit proxies and private-network endpoints are not accepted. IMAP uses a read-only folder and `BODY.PEEK`. Connection status exposes no credentials. The local demo does not implement provider onboarding. The separate service adds Zendesk OAuth; unrestricted public webhooks and customer submission forms remain out of scope.

## Reporting

Use the repository's private security reporting channel if the maintainer enables one. Do not paste credentials, personal tickets, databases or exploit payloads containing private data into public issues. No personal contact address is embedded in this template.

## Authenticated service

Workspace-scoped SQL queries isolate ticket state, provider configuration, API keys, sessions and sync cursors. Passwords use salted scrypt; session/API/invitation tokens are random and stored as hashes. HTTPS sessions use Secure, HttpOnly, SameSite=Lax host cookies. Browser mutations require exact Origin and CSRF; REST uses scoped expiring keys. Members cannot administer credentials or invitations, and viewers cannot mutate tickets.

Connection secrets and OAuth verifiers/tokens use Fernet authenticated encryption with workspace context and an operator-owned key file. Ticket text and database backups are not encrypted by the application. PKCE state is one-use, expiring and bound to the initiating session. Refresh rotation is serialized within one replica. Sync stores each page and cursor atomically, retains progress on failure and never calls an AI provider.

Durable idempotency records prevent identical completed REST requests from repeating model calls during the retention window. Uncertain pending requests are not automatically replayed. Run one replica; add HTTPS, edge quotas, disk encryption, tested backups and operational monitoring. These controls and regression tests do not constitute a penetration test or an enterprise SaaS security certification.
