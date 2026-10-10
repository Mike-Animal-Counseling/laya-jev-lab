# Attribution and licenses

The demo source is provided under Apache License 2.0; see `LICENSE`. Third-party components retain their respective licenses. No personal author name or email is required by the demo's own distribution files.

## Laya runtime

`ticket_engine/_vendor/laya/` retains the reviewed Laya 0.3.5 runtime source from the upstream project at revision `573e5b62696ba441230cd6be71d593331b5d23af`. Its Apache-2.0 license is preserved in `ticket_engine/_vendor/LICENSE`. Local modifications in `agent.py` and `common.py` require existing local model files, disable remote downloads/token discovery, and avoid mutating tokenizer configuration. Model construction uses the PyTorch meta device followed by strict checkpoint assignment, then recreates ModernBERT's non-persistent rotary buffers; this avoids unnecessary random initialization and a Windows initialization crash observed during testing. These changes support embedding without process-wide environment changes. The other vendored files are unchanged. Model verification and engine adapters live in `ticket_engine/`; `projects/` contains demo-specific lifecycle/configuration adapters.

- Source: https://github.com/NandhaKishorM/laya
- Author/organization identified by the upstream package: Convai Innovations
- Model: https://huggingface.co/convaiinnovations/laya
- Multilingual encoder: https://huggingface.co/jhu-clsp/mmBERT-base

Upstream names, public repository identifiers and license notices are attribution, not the local operator's personal identity. They are intentionally retained.

## Fine-tuned checkpoint

The model card identifies the fixed V5 derivative and its limitations. The upstream Laya model card identifies Apache-2.0; the mmBERT model card identifies MIT. These are distinct component licenses. The inference artifact includes this notice, the Apache license and the MIT terms in `licenses/mmbert-MIT.txt`; raw training datasets are not redistributed here.

## Jev

Jev is an external TypeSafe API. Its service, account, billing and terms are separate from this repository's source license. This repository is an independent comparison demo and does not claim endorsement by either model provider.
