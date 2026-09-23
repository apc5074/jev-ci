# Phase 1 verification record

Exercised on 2026-09-22 from the repository root using only the commands in [setup.md](setup.md). Host Java/Python/Perl/Defects4J were not used. The prior `jev-ci:phase1` tag was removed first so the run started from a newly tagged image (Docker layer cache reused for unchanged Dockerfile steps).

## Commands run

```bash
docker rmi jev-ci:phase1   # optional; ensure a fresh tag
docker build --platform linux/amd64 -t jev-ci:phase1 .
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 \
  python scripts/check_environment.py
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 \
  defects4j info -p Lang
```

## Results

| Step | Outcome |
| --- | --- |
| `docker build … -t jev-ci:phase1 .` | Succeeded |
| `python scripts/check_environment.py` | Exit 0; wrote `results/environment.json` |
| `defects4j info -p Lang` | Exit 0; Lang, 61 bugs |
| Repo reachable at `/workspace` | `config/`, `scripts/`, `results/environment.json` present |
| Writable `data/`, `cache/`, `results/` | Small probe files written successfully |

## Observed environment (from `results/environment.json`)

| Field | Value |
| --- | --- |
| Defects4J | 3.0.1 @ `6d54320e0db5a357f9ab38a8e4d2e5aead7e1c09` |
| Python | 3.12.14 |
| Java | 11.0.32.1 |
| OS | Ubuntu 22.04.5 LTS |
| Architecture | x86_64 (`linux/amd64`) |
| Timezone | America/Los_Angeles |

## Caveats

- First cold build needs network and several minutes for Defects4J `init.sh`; subsequent builds are much faster when layers are cached.
- On Apple Silicon, `--platform linux/amd64` is required and runs under emulation.
- Phase 1 needs no API keys.

## Phase 1 gate

Phase 1 is complete. Phase 2 can start from the handoff in [setup.md](setup.md): image `jev-ci:phase1`, path contract, Defects4J pin, and `results/environment.json`.
