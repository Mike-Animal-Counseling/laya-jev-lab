# Changelog

## 0.2.0

- Independent `LayaEngine` and `JevEngine` entry points, JSON CLI and dependency-free `ServiceClient`. Existing `TicketEngine` calls remain compatible.
- Workspace-scoped REST classification/import/upsert endpoints, scoped expiring keys, OpenAPI contract and durable UUID retry protection.
- Optional authenticated service: isolated workspaces, owner/member/viewer roles, invitations, session revocation and encrypted connection settings.
- Zendesk OAuth with PKCE, expiring tokens, refresh rotation and disconnect; persisted incremental sync with pause, backoff, source updates and atomic cursor commits.
- English login/settings screens, viewer controls, shared inbox refresh and Docker/HTTPS deployment instructions.
- Service security regression tests and container smoke CI. Provider tests use mocks; real-account OAuth needs operator configuration.

The V5 inference files and model notices remain unchanged. Use the reviewed v0.1.0 model asset with this version. Import/sync never calls AI, and the service never modifies Zendesk tickets. Supported shared deployment: one SQLite API replica for small teams.

## 0.1.0

Initial public release: trained local Laya V5, Jev comparison, independent classification SDK, English local inbox, Excel/CSV/email intake and bounded source adapters. Source and inference assets were separately reviewed and published with checksums.
