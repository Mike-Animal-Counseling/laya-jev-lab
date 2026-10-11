# Contributing

This project focuses on SaaS ticket classification and comparing fine-tuned Laya V5 with Jev under a shared rubric. Useful contributions include classifier integrations, intake adapters, reliable evaluation with synthetic or appropriately reviewed data, and clearer inbox interactions.

## Development

Follow the README installation steps. Backend and UI checks do not require live provider credentials:

```sh
python -m pip install --require-hashes -r backend/requirements.lock
python -m unittest discover -s backend -p "test_*.py"
python -m unittest discover -s tests -p "test_*.py"
npm run test:ui
npm run lint
npm run build
npm run typecheck
python scripts/check_public.py
```

The optional tiny-model test runs when local inference dependencies are installed. For frontend development, run `python backend/server.py` and `npm run dev` in separate terminals.

Keep changes within the supported [classification scope](SCOPE.md). Preserve engine isolation, revision checks and explicit external model calls. Rule changes can invalidate the pinned model rubric and require a corresponding model release. Adapter requirements and current connector limits are in [INTAKE.md](INTAKE.md).

## Review and publication

Use synthetic tickets in tests, screenshots and issues. Keep `.env.local`, `var/`, models, raw datasets and private logs out of Git. New source files must be explicitly added to `release-files.json` and reviewed; `.gitignore` does not protect already tracked files.

```sh
git config core.hooksPath .githooks
python scripts/check_public.py --staged --identity
```

Use your intended public author identity and GitHub privacy email. On macOS/Linux, also make `.githooks/pre-commit` executable. Describe the behavior change and relevant validation in pull requests. Report security issues privately using the repository's Security tab.

To create an allowlisted source archive, use a new output filename:

```sh
python scripts/export_source.py ../laya-jev-lab-source.zip
```

Model artifacts are separate Release assets, with matching source notices and pinned inference hashes. Changes to code or model notices require a matching artifact review before publishing a new version.
