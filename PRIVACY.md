# Privacy and data boundaries

## What ships

The source distribution contains application code, clean reusable training tools, synthetic fixtures, unit tests, blank credential configuration, dependency manifests, documentation and reviewed upstream runtime source. It contains no original workspace database, ticket exports, raw training/evaluation datasets, original training notebooks, local logs, cached API responses, credentials, personal directories or inherited Git history.

Synthetic fixture identities are explicitly numbered demo users and example teams. The examples do not represent actual customers. Tests use temporary stores and fake adapters.

## Runtime

Laya inference is local. The private runtime requires verified local files and passes local-only/no-token options to model loaders. It never automatically downloads missing weights or changes the integrating application's environment variables. Next.js telemetry is disabled by the provided launcher. Installation commands still contact public package registries; this is different from inference sending ticket contents.

The standalone SDK has no ticket store or credential discovery: callers explicitly provide a model path or API key. Its results omit original ticket text and credentials. Demo persistence and `.env.local` configuration described below belong to the optional web app.

Jev is an external API. The interface discloses that an explicit analysis action sends the selected ticket's subject and message, the fixed task questions, model identifier and the operator's API credential to TypeSafe over HTTPS. Opening the comparison view does not itself invoke a model. Batch analysis sends each selected pending ticket until stopped. Redirects and implicit system proxy configuration are disabled.

No creator-owned credential or account is supplied. The local demo operator configures `.env.local`; the shared-service operator configures each workspace through Settings. The backend does not read parent-workspace credentials or environment API keys. No credential is returned in API responses or analysis exports.

New ticket contents, results and history persist in `var/`. They are excluded from source export. Browser downloads are outside this protection: exported results may contain any personal information the operator entered. The application does not anonymize arbitrary free text before API calls or export.

## Deletion

Stop the demo before deleting its `var/` directory to remove its database and backups. Resetting demo tickets creates a backup and is not an erasure action. Remove this project's `.env.local` separately to remove the locally stored Jev credential. Review any browser downloads separately. These operations do not revoke a credential at the provider or erase data already sent to the provider.

## Intake connections

Excel/CSV/email preview uploads are parsed in memory; files are not stored. Confirmed rows are saved to the same local ticket database. Email attachments are ignored and HTML bodies are converted to text. These inputs may contain personal information; the source release ships only synthetic examples.

Optional Zendesk/REST/IMAP settings are read only from this repository's `.env.local`. Credentials are sent only to the explicitly configured verified TLS destination when the operator clicks Sync, and are never returned to the browser or included in exported tickets. Sync reads external data into a preview; it does not send replies, alter the source system, call an AI model or automatically save the preview. See [INTAKE.md](INTAKE.md).

## Publishing

Use the allowlisted source archive or its independently initialized repository. Do not add runtime state, screenshots containing personal data, shell transcripts, unrelated notebooks, local IDE settings, or unreviewed artifacts. Git author names/emails and commit messages are public metadata and need their own review; configure a chosen public identity and GitHub privacy email before the first commit.

Source scanning and safetensors metadata review cannot prove the absence of every possible secret or that learned parameters never encode training information. The packaged model is a fixed-label classifier and does not generate free-form text, but this is not a mathematical privacy guarantee.

## Shared service storage

The optional authenticated deployment stores workspace tickets, results, users, metadata audit events, sync progress and idempotency records in `var/cloud/` or a private Docker volume. Settings are encrypted with a private `master.key`; ticket text is not application-encrypted. Passwords and session/API/invitation tokens are hashed. Secret values are shown only at creation when appropriate, never returned as saved settings.

Stateless `/v1/classify` stores its result and input digest, not the original subject/body. Imported inbox tickets retain their original content. Exports, backups and caches may contain personal data. Removing an inbox record is not comprehensive erasure of source data, backups or request caches. Operator retention/deletion guidance is in [DEPLOYMENT.md](docs/DEPLOYMENT.md). New workspaces contain no original-author tickets or credentials.

## Optional training

An owner can explicitly authorize sanitized labelled tickets to be sent to their own private Kaggle dataset for GPU training. This is an external data transfer. Preview drops unused identity columns and masks common email/phone/token patterns; it cannot remove every sensitive detail. Review input before uploading. Kaggle receives remaining text and labels. Tasks and datasets remain in that account until deleted there; stopping local tracking does not cancel a GPU job or erase remote data.

Preview snapshots and Kaggle tokens are encrypted in the service database. Sanitized job bundles and adapters in private `var/cloud/training/` files are not application-encrypted. Backups must protect this directory together with the database and separate encryption key. Adapter downloads contain decision weights and aggregate evaluation, not raw tickets or credentials, but learned weights are not a privacy guarantee. Do not publish customer-derived adapters without a separate review. See [TRAINING.md](docs/TRAINING.md) for setup, limits, disconnect and retention.
