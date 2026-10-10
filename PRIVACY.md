# Privacy and data boundaries

## What ships

The source distribution contains application code, synthetic fixtures, unit tests, blank credential configuration, dependency manifests, documentation and reviewed upstream runtime source. It contains no original workspace database, ticket exports, raw training/evaluation datasets, training notebooks, local logs, cached API responses, credentials, personal directories or inherited Git history.

Synthetic fixture identities are explicitly numbered demo users and example teams. The examples do not represent actual customers. Tests use temporary stores and fake adapters.

## Runtime

Laya inference is local. The private runtime requires verified local files and passes local-only/no-token options to model loaders. It never automatically downloads missing weights or changes the integrating application's environment variables. Next.js telemetry is disabled by the provided launcher. Installation commands still contact public package registries; this is different from inference sending ticket contents.

The standalone SDK has no ticket store or credential discovery: callers explicitly provide a model path or API key. Its results omit original ticket text and credentials. Demo persistence and `.env.local` configuration described below belong to the optional web app.

Jev is an external API. The interface discloses that an explicit analysis action sends the selected ticket's subject and message, the fixed task questions, model identifier and the operator's API credential to TypeSafe over HTTPS. Opening the comparison view does not itself invoke a model. Batch analysis sends each selected pending ticket until stopped. Redirects and implicit system proxy configuration are disabled.

No creator-owned credential or account is supplied. Each operator must configure their own `.env.local`. The backend does not read parent-workspace credentials or environment API keys. No credential is returned in API responses or analysis exports.

New ticket contents, results and history persist in `var/`. They are excluded from source export. Browser downloads are outside this protection: exported results may contain any personal information the operator entered. The application does not anonymize arbitrary free text before API calls or export.

## Deletion

Stop the demo before deleting its `var/` directory to remove its database and backups. Resetting demo tickets creates a backup and is not an erasure action. Remove this project's `.env.local` separately to remove the locally stored Jev credential. Review any browser downloads separately. These operations do not revoke a credential at the provider or erase data already sent to the provider.

## Publishing

Use the allowlisted source archive or its independently initialized repository. Do not add runtime state, screenshots containing personal data, shell transcripts, unrelated notebooks, local IDE settings, or unreviewed artifacts. Git author names/emails and commit messages are public metadata and need their own review; configure a chosen public identity and GitHub privacy email before the first commit.

Source scanning and safetensors metadata review cannot prove the absence of every possible secret or that learned parameters never encode training information. The packaged model is a fixed-label classifier and does not generate free-form text, but this is not a mathematical privacy guarantee.
