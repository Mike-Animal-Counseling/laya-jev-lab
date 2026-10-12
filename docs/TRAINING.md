# Train Laya on your tickets

Connect your own Kaggle account once, import labelled historical tickets in **Settings → Train**, and start training from the app. The service uploads a private dataset, starts a private GPU task, checks status and retrieves the candidate. Normal runs need no notebook editing, Run All step or manual transfer.

This release continues from the reviewed **Laya V5**, adjusting decision layers while freezing the encoder and action head. It retains the five existing SaaS categories. It is not full encoder fine-tuning or a promise that every dataset will improve V5. Jev remains independent.

## Setup

Use the authenticated workspace service, on your own computer or through [Docker](DEPLOYMENT.md). Only owners can manage training or download adapters. The single-user demo backend does not provide training routes. Integration keys cannot control training.

Docker includes the coordinator and Kaggle connector. The application host needs CPU inference dependencies and the unchanged V5 weights, but no GPU. Training uses the connected Kaggle account's GPU quota. Account verification, accelerator access, internet access, quota and availability remain Kaggle requirements; the app cannot bypass them.

For a source checkout with Python 3.12 and the README's Laya CPU runtime already installed:

```sh
python -m pip install --require-hashes --index-url https://pypi.org/simple -r service/requirements.lock
python -m pip install --require-hashes --index-url https://pypi.org/simple -r service/kaggle.lock
python -m service.manage init --workspace demo --owner admin
python -m service.server
```

Initialization prompts for your own password. In a second terminal, run `npm ci` and `npm run dev`. Open `http://127.0.0.1:5180/laya-ft` and sign in. Do not run the demo backend on the same API port. Remote deployments require HTTPS.

In **Settings → Train**, enter your lowercase Kaggle username and a token from [Kaggle API settings](https://www.kaggle.com/settings/api), then **Connect**. This release supports modern API tokens, not uploaded legacy `kaggle.json` files. The connector verifies access and rejects a token whose detected username differs from the supplied account.

Tokens are encrypted in workspace settings. They never enter datasets, training code, metadata, command-line arguments or downloads. The official SDK runs in an isolated process with an empty credential directory and only the supplied account. **Disconnect** removes the saved token after active tracking ends; it does not revoke the token at Kaggle or delete remote data.

## Labelled data

Use the **CSV template** or the first sheet of an Excel `.xlsx`. CSV must be UTF-8; `.xls`, formulas, macros and external workbook links are rejected. Limits: 2 MB, 20–2,000 tickets, 12 columns, and at least two categories with 10 distinct conversation groups each. This minimum permits splitting, not reliable accuracy claims. Use substantially more representative, human-reviewed examples for real routing decisions.

| Column | Meaning |
| --- | --- |
| `subject` | Optional title, up to 120 characters |
| `message` | Required problem text, up to 3,000 characters |
| `category` | Required: `refund`, `technical`, `sales`, `account` or `other` |
| `group_id` | Conversation identifier; keep messages from one conversation together |
| `ticket_id` | Fallback identifier when `group_id` is absent |
| `urgency` | Optional integer: `0`, `1`, `2` or `3` |
| `complaint`, `churn`, `refund` | Optional: `true`, `false`, `1` or `0` |

Map your helpdesk's labels to the existing rubric first. Category `refund` covers billing/refund issues; the optional `refund` column separately labels refund intent. New category definitions require another model/rubric change. Do not treat the model's predictions as verified human labels.

Empty optional labels stay unknown. Optional fields train only when all three splits have at least two labelled outcomes; otherwise their decisions and temperatures remain exactly on V5. Provide conversation identifiers for exported threads. Duplicate normalized text after masking and conflicting categories within one conversation are rejected.

Preview drops unused identity columns, masks emails, common international/Chinese phone patterns and known token patterns, and hashes group identifiers. **Basic masking is not comprehensive anonymization**: names, addresses, internal links and other secrets can remain. Sanitize the file before uploading it to the application. The checkbox explicitly authorizes transfer to your private Kaggle dataset.

## Train and choose

1. Choose your file and review counts, trained/unchanged fields and missing categories.
2. Confirm private Kaggle upload, then **Train**. You can leave the page; the service must keep running to coordinate and retrieve results.
3. Review the held-out comparison. **Use model** is enabled only for a verified candidate that passes the improvement rule. No model switches automatically.
4. **Restore V5** restores the default in this workspace. **Download** exports the adapter for independent SDK use.

Splitting is deterministic and grouped by conversation, approximately 60% train / 20% validation / 20% test within represented categories. Validation alone selects epochs and confidence temperatures; test data selects neither. Training uses microbatches, accumulated gradients, up to three epochs and a three-hour optimization limit. The private task downloads and hash-verifies the immutable public V5 archive; it never uploads creator training data or your application's base weights.

Reports show macro F1, category recall and held-out counts. Mean macro F1 must improve by more than 0.001, no trained field may lose more than 0.02 macro F1, and no represented class may lose more than 0.15 recall. Missing categories remain unevaluated. This gate is not a statistical significance test or a production accuracy guarantee. Urgency evaluation uses the highest-scoring discrete label; serving retains the probability-weighted urgency score. Check operational priority thresholds separately.

The best validation checkpoint can be epoch zero, so successful training may keep V5 when it already handles the sample well. A frozen encoder can also limit improvement for unfamiliar language or terminology.

Model selection affects future Laya calls, including `/v1/classify`, in this workspace. Other workspaces and Jev retain their configurations. Old analyses keep their model IDs and need re-analysis before assignment. Import, sync, enabling and restoring models never automatically invoke AI.

## Recovery and storage

A workspace tracks one active job. Stable request IDs protect repeated clicks. A submission attempt is persisted before contacting Kaggle; timeouts and restarts reconcile that same task instead of automatically spending quota on a second submission. **Check status** checks/retrieves the existing task.

For an inaccessible or missing task, inspect its linked Kaggle page. Stop any running task there before **End tracking**. This only ends local tracking; it does not cancel GPU usage or delete remote data. Start another run after resolving the previous one. Quota and verification problems may still require visiting Kaggle.

Datasets and tasks are private by default and remain in your Kaggle account until you delete them there. Kaggle receives the sanitized training text and labels. Local previews are encrypted in SQLite. Bundles, sanitized snapshots and adapters under `var/cloud/training/` are private files but not application-encrypted. Keep them out of Git, public releases and screenshots. Customer-derived weights may encode training information and need separate review before publication.

Back up the database, matching `master.key` and training directory together in private storage; enabled adapters need that directory after restoration. Limits are 20 job records and 30 dataset snapshots per workspace. Operators must establish retention and archive/remove inactive records and files under a stopped service when necessary. This does not erase Kaggle data or backups.

## Independent SDK and local training

Unzip the three-file download into a private directory:

```python
from ticket_engine import LayaEngine

engine = LayaEngine(
    model_path="models/ticket-finetuned-v5",
    adapter_path="private-models/my-team",
)
engine.prepare()
result = engine.classify("Please help fix the failed export.", subject="Export error")
print(result.to_dict())
```

The adapter requires the exact reviewed V5. Loading checks rubric/base identities, hashes, tensor names, shapes and finite values. Only decision-layer safetensors are accepted, never pickle or replacement encoder/action tensors. Remove `adapter_path` to restore V5. Adapted `checkpoint_sha256` is the SHA256 identity of the canonical adapter manifest, including base/tensor hashes, calibrated temperatures, trained fields and dataset provenance; model names begin `laya-ticket-adapted-`.

The SDK has no Kaggle/service/UI dependency. Training tools belong to this source repository, not the SDK wheel. Local training with an existing Python 3.12+ Torch installation is also supported:

```python
from pathlib import Path
from training.data import encoded, parse_upload

value = parse_upload(Path("private-tickets.csv").read_bytes(), "text/csv")
Path("private-dataset.json").write_bytes(encoded(value))
```

```sh
python -m pip install --require-hashes --index-url https://pypi.org/simple -r training/requirements.lock
python -m training.runner --base models/ticket-finetuned-v5 --data private-dataset.json --output private-result --device auto
```

Supply your own CPU/CUDA Torch 2.6+; the lock preserves Kaggle's GPU Torch instead of installing a CPU wheel. Choose an empty output directory. CPU training is useful for small evaluations, with greater runtime than GPU training.

## Validation

Tests cover grouping, missing labels, owner/CSRF checks, account isolation, credential encryption, submission recovery, result verification and original-field preservation. Actual V5 with synthetic labelled tickets passed local CPU training, export and SDK loading, preserving original weight hashes. Provider checks use mocks and the pinned official SDK interface. No live Kaggle GPU or customer dataset was used; real-account acceptance testing remains necessary before claiming compatibility with a particular image/quota configuration.

References: [official API](https://github.com/Kaggle/kaggle-cli), [kernel metadata](https://github.com/Kaggle/kaggle-cli/blob/main/docs/kernels_metadata.md), [datasets](https://github.com/Kaggle/kaggle-cli/blob/main/docs/datasets.md), [GPU runtime](https://github.com/Kaggle/docker-python/blob/main/Dockerfile.tmpl).
