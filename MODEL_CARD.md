# Laya ticket V5

## Purpose

A fine-tuned multilingual ticket classifier derived from the Laya multilingual checkpoint, used alongside Jev to compare SaaS support-triage decisions. It predicts category, urgency, complaint, churn and refund signals under the exact rules in `ticket_engine/rules.py`. It does not generate replies or independently perform business actions.

The inference checkpoint identity and every configuration/tokenizer file hash are in `ticket_engine/model-manifest.json`. The weight SHA256 is `c4ee793b468368c257a152cd4c42ea5e95dd867fdd9eced21e752cae1b5d019f`.

## Training provenance

The retained training manifest records 953 updates, continuation from V4, and RLCD with a smoothed classification objective. Its local labels are synthetic, not independently verified production ground truth. The V5 recipe used 720 local examples and a first-epoch public-data warmup with 2,250 weakly labelled examples at reduced weight. Calibration and regression splits were reused; they are not fresh independent validation sets.

The release intentionally contains no raw examples, optimizer state, notebook execution history, private evaluation caches or training history files. Its inference manifest preserves identity, rules and limitations, while excluding workstation and execution metadata.

## Interpretation

- Scores and thresholds depend on the chosen rules. Complaint definitions can cause disagreement between Laya and Jev.
- Confidence is a model output, not measured accuracy on a user's tickets.
- The interactive comparison is not a statistically representative evaluation or proof of parity with Jev.
- Evaluate independently labelled, representative tickets for each intended language and workflow before relying on routing suggestions.
- The V5 tokenizer context is limited; long tickets can be truncated during inference.
- No differential privacy or formal training-data non-memorization guarantee is claimed.

## Distribution

The inference ZIP contains five required inference files, a reduced `training_manifest.json`, and four license/model notices; its weight tensor data is unchanged. The importer requires hashes pinned in the source release, checks the notices against the source release, rejects additional files and never substitutes base-model weights. A checksum establishes integrity relative to the reviewed source, not independent authenticity if an attacker controls both.

Source code and weights are distributed separately in the [v0.1.0 release](https://github.com/Mike-Animal-Counseling/laya-jev-lab/releases/tag/v0.1.0). Use the matching source tag and `laya-v5-inference.zip`; the release also supplies `SHA256SUMS.txt` for the archive. Model loading never downloads missing files automatically.

Upstream sources and licenses are identified in [NOTICE.md](NOTICE.md). This project does not redistribute raw public training datasets and does not claim ownership of upstream models or the Jev service.
