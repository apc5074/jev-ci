# Setup (Phase 1)

Build and run the reproducible Linux environment for the Jev CI experiment. Host Java, Python, Perl, or Defects4J are **not** required.

Related contracts: [environment.md](environment.md) (paths), [toolchain.md](toolchain.md) (pins), [python.md](python.md) (script invocation), [environment-record.md](environment-record.md) (smoke check).

## Prerequisites

- Docker with `linux/amd64` support (Apple Silicon uses emulation)
- Network access on first build (Defects4J downloads project repos and tool JARs)
- Disk: several GB for the image after Defects4J init

## Build

From the repository root:

```bash
docker build --platform linux/amd64 -t jev-ci:phase1 .
```

**Time / network:** the first build typically takes several minutes. Most of that is Defects4J `cpanm --installdeps .` and `./init.sh` (large downloads). Later rebuilds reuse layers unless `Dockerfile`, `config/defects4j.pin`, `scripts/install_defects4j.sh`, or `requirements.txt` change.

**Failed build:** fix the error and re-run the same `docker build` command. Docker layer caching resumes after the last successful step. To force a full Defects4J reinstall:

```bash
docker build --platform linux/amd64 --no-cache -t jev-ci:phase1 .
```

No API keys are required to build.

## Run (bind-mounted checkout)

```bash
docker run --rm -it \
  --platform linux/amd64 \
  -v "$(pwd):/workspace" \
  -w /workspace \
  jev-ci:phase1
```

Inside the container, cwd is `/workspace` (this repository). Defects4J is at `/opt/defects4j` (`D4J_HOME`). Durable outputs go under `data/`, `cache/`, and `results/` on the host via the mount.

One-shot command form (no interactive shell):

```bash
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" \
  -w /workspace \
  jev-ci:phase1 \
  <command>
```

## Smoke check

```bash
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" \
  -w /workspace \
  jev-ci:phase1 \
  python scripts/check_environment.py
```

Expected: exit `0`, message `environment ok`, and `results/environment.json` written on the host.

Optional Defects4J probe (also covered by the smoke check):

```bash
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" \
  -w /workspace \
  jev-ci:phase1 \
  defects4j info -p Lang
```

## Phase 2 handoff

Dataset split is locked in `data/manifest.json`. Phase 3 instructions: [phase3-handoff.md](phase3-handoff.md). Verification record: [verification-phase2.md](verification-phase2.md).

```bash
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 \
  python src/select_bugs.py verify
```

| Item | Value |
| --- | --- |
| Image tag | `jev-ci:phase1` |
| Platform | `linux/amd64` |
| Invocation | bind-mount repo at `/workspace`, run `python …` |
| Defects4J | `3.0.1` at commit in `config/defects4j.pin` (`/opt/defects4j`) |
| Path contract | [environment.md](environment.md) |
| Environment record | `results/environment.json` |

Later API keys (if needed) are injected at runtime only; see [environment.md](environment.md).

## Diagnosis

| Symptom | What to check |
| --- | --- |
| Build fails in `install_defects4j.sh` / `init.sh` | Network to GitHub and `defects4j.org`; retry build |
| `defects4j: command not found` | Use the image above; do not rely on host PATH |
| Smoke check fails on `TZ` / Java / commit | Rebuild from this repo; do not override `TZ`/`JAVA_HOME` unless debugging |
| Cannot write `results/` | Ensure the repo mount includes writable `data/`, `cache/`, `results/` |
