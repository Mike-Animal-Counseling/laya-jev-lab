# Public-source preparation review

Prepared: 2026-10-04. Scope: this independently packaged Laya V5 / Jev demo and its matching inference artifact, not the maintainer's original development workspace or a future public hosting environment.

## Changes made

- Created a source allowlist rather than copying a development workspace recursively.
- Excluded credentials, ticket databases/backups, evaluation outputs, training data/notebooks, execution logs, platform/IDE settings, dependencies, build outputs and old Git history.
- Replaced example customer identities with numbered synthetic identities and replaced the binary favicon with a small inspectable SVG.
- Removed the legacy base-model route and its dependency on scripts and models outside the repository.
- Fixed runtime storage and model lookup to this repository; Jev reads only this repository's explicitly configured credential file.
- Used independent loopback ports and a launcher that rejects occupied ports rather than connecting to another workspace's service.
- Removed unnecessary development dependencies that introduced a known advisory. The complete npm audit now reports no known vulnerabilities.
- Added blank configuration, privacy/security/model documentation, preserved third-party notices, and an allowlisted source exporter.
- Added Git-index scanning and an optional commit identity gate requiring a GitHub privacy email; original commit authors and history are not copied.

## Evidence

| Check | Result |
| --- | --- |
| Source allowlist and secret/path/email patterns | Passed |
| Exact comparison against the original private key and workstation identifiers | Zero matches; values never copied into reports or scanner source |
| Model configuration/tokenizer private-value scan | Passed |
| safetensors arbitrary metadata | Empty; tensor names also checked |
| Model archive import and pinned file hashes | Passed |
| Backend/security/privacy tests | 40 passed; temporary data and fake providers |
| Frontend interaction tests | 8 passed; no external API |
| ESLint, production build, TypeScript | Passed |
| Complete npm dependency advisory check | 0 known vulnerabilities, including development dependencies |
| Real V5 inference from the sanitized archive | Passed, all five outputs; external socket connections blocked during verification |
| Jev during isolated verification | Unconfigured; no private account or live API used |
| Public app routes | Both model pages returned 200 |
| Sensitive file URL probes | 404 for credential, database, backend source, model weights and vendored source paths |
| Cross-origin/session and missing-CSRF probes | 403 |

The verification process was stopped afterward. Its database, model extraction, logs, dependencies and build outputs are not part of the source distribution. The reviewed weights remain in a separate inference ZIP.

## Limits and next step

This is preparation for publication, not an assertion of absolute safety. Secret pattern matching cannot prove the absence of all personal information, model metadata checks do not prove that parameters contain no learned information, and known-advisory counts change. No visual browser acceptance or public-hosting penetration test is claimed here.

Create a fresh repository from this source directory with an intended public alias and GitHub privacy email, then run the staged and identity checks before the first commit. Publish the reviewed inference ZIP as a matching release asset if distributing weights. No GitHub upload, remote configuration or commit was performed during preparation.

Re-audit additions and changed dependencies. Do not add real tickets or a creator-owned API key to make a public demo easier to operate; each operator supplies their own credentials and uses synthetic examples.


## Integration module follow-up

The deliverable now includes an installable `ticket_engine` package with a shared five-category SaaS scope, explicit local model/API-key configuration, typed JSON-serializable results, safe errors and an explicit comparison function. The optional web demo reuses the package's rules, normalization, model verification, local loader and Jev transport. Documentation makes clear that `other` is not an uncertainty or out-of-domain detector.

Additional checks: 13 SDK contract tests passed alongside the 40 backend/security tests. The package builds as a Python wheel and imports from an independent installation without the demo, SQLite or the ML stack. No dependency was added to the base SDK; local inference dependencies are optional. Frontend source and its dependency lock were not changed in this follow-up, so the earlier frontend build/interaction and npm audit results are retained rather than claimed as a new run.

The independently installed wheel also performed genuine local classification with outbound socket connections disabled: the synthetic duplicate-charge example returned the billing/refund category with the pinned checkpoint identity and all five signals. This verification did not import the demo server. PyTorch may import standard-library SQLite utilities internally; the SDK itself has no ticket persistence or database connection code.
# v0.2.0 implementation review

The earlier sections below record historical v0.1.0 preparation; their counts and publication status are not current release claims. The v0.2.0 follow-up adds independent engine adapters, REST integration and an optional authenticated workspace service.

Reviewed additions: synthetic service fixtures, blank provider settings, workspace-scoped persistence, hashed passwords/tokens, encrypted connection settings, PKCE state/session binding, refresh rotation, cursor commit/retry behavior, roles and request idempotency. All 138 declared source files pass the publication scanner. The new settings screenshot contains only a synthetic workspace/account and empty connection fields; PNG chunks contain image data only. Runtime databases, QA credentials, downloads and models are excluded.

Validation: 25 service tests and 5 adapter tests, existing SDK/runtime checks, 61 backend tests and 12 React interaction tests; lint, types and both production container builds. A real Docker run imported the reviewed model ZIP, classified synthetic tickets with the pinned checkpoint, and verified login, scoped API keys, cached retries, invitations, viewer permissions, workspace isolation and mobile layout. An independent wheel installation imported Jev without Torch, web or service dependencies. Service and 41 CPU deployment package advisory checks, plus the complete npm audit, reported no known vulnerabilities at review time.

The model files and four required notices are unchanged. OAuth protocol tests use mocks; real Zendesk account authorization and public DNS/TLS configuration require the operator's own client/account/domain. This review is not a penetration test, an independent model benchmark or proof of absolute privacy. New source, wheel and checksums are prepared for review; this does not declare a v0.2.0 public Release.

