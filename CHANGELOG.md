# Changelog

## Unreleased

- Train Laya V5 on labelled CSV/Excel from Settings: own-account Kaggle connection, private GPU tasks, durable status reconciliation and verified candidate downloads.
- Grouped train/validation/test splits, basic masking, missing-label handling, held-out improvement gate and explicit model selection or V5 restore per workspace.
- Optional decision-layer adapters in the independent `LayaEngine`; original encoder, action head and unlabelled decision fields remain on V5. Jev stays independent.
- Owner-only training routes, encrypted account tokens, bounded artifact downloads and submission retry protection. No creator Kaggle credential or customer training data is bundled.
- Adapter identity pins calibration and trained-field metadata as well as weights; official Kaggle startup/cancellation states reconcile explicitly.
- Chinese end-to-end usage/testing guide and a private synthetic example generator for intake, API and training previews.

Actual V5 CPU training and adapter loading were validated with synthetic data. Kaggle GPU acceptance remains a real-account check; provider regression tests use mocks. The public V5 model asset is unchanged.

## 0.2.0

- Independent `LayaEngine` and `JevEngine` entry points, JSON CLI and dependency-free `ServiceClient`. Existing `TicketEngine` calls remain compatible.
- Workspace-scoped REST classification/import/upsert endpoints, scoped expiring keys, OpenAPI contract and durable UUID retry protection.
- Optional authenticated service: isolated workspaces, owner/member/viewer roles, invitations, session revocation and encrypted connection settings.
- Zendesk OAuth with PKCE, expiring tokens, refresh rotation and disconnect; persisted incremental sync with pause, backoff, source updates and atomic cursor commits.
- Explicit ticket-read scopes on token exchange/refresh; reactive refresh requires a confirmed invalid-token response, not a permission failure.
- English login/settings screens, viewer controls, shared inbox refresh and Docker/HTTPS deployment instructions.
- Service security regression tests and container smoke CI. Provider tests use mocks; real-account OAuth needs operator configuration.

The V5 inference files and model notices remain unchanged. Use the reviewed v0.1.0 model asset with this version. Import/sync never calls AI, and the service never modifies Zendesk tickets. Supported shared deployment: one SQLite API replica for small teams.

## 0.1.0

Initial public release: trained local Laya V5, Jev comparison, independent classification SDK, English local inbox, Excel/CSV/email intake and bounded source adapters. Source and inference assets were separately reviewed and published with checksums.
