# Jev CI test-selection experiment

Static regression-test prioritization experiment using Defects4J 3.0.1 and the Jev decision model. Design and rules live in `Plans/overall.md`.

## Quick start

```bash
docker build --platform linux/amd64 -t jev-ci:phase1 .
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 \
  python scripts/check_environment.py
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 \
  python src/select_bugs.py verify
```

## Docs

| Doc | Contents |
| --- | --- |
| [docs/setup.md](docs/setup.md) | Build, run, smoke check |
| [docs/phase3-handoff.md](docs/phase3-handoff.md) | Locked split for Phase 3 |
| [docs/verification-phase2.md](docs/verification-phase2.md) | Manifest lock record |
| [docs/manifest.md](docs/manifest.md) | Manifest schema / create / verify |
| [docs/testing.md](docs/testing.md) | Phase 2 unit tests |
| [docs/example-contract.md](docs/example-contract.md) | Phase 3 example layout and visibility |
