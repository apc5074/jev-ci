# Environment and path contract

Canonical container layout and environment for the Jev CI experiment. Later phases and scripts must use these paths and variables; do not introduce host-home paths.

## In-container paths

| Role | Path | Lifetime |
| --- | --- | --- |
| Working directory / repository root | `/workspace` | Bind-mounted from the host checkout for development |
| Defects4J installation | `/opt/defects4j` | Baked into the image at build time |
| Defects4J CLI (`framework/bin`) | `/opt/defects4j/framework/bin` | On `PATH` in the image |
| Experiment data (manifest, bugs, patches, tests, candidates) | `/workspace/data` | Host-backed via the `/workspace` mount |
| Request / embedding caches | `/workspace/cache` | Host-backed via the `/workspace` mount |
| Results, figures, environment record | `/workspace/results` | Host-backed via the `/workspace` mount |

`/opt/defects4j` is intentionally outside `/workspace` so the Defects4J checkout is not mixed with project sources or generated artifacts, and so a bind mount of the repository cannot overwrite the installation.

Host home directories (`$HOME`, `~`, `/Users/...`, `/home/...`) must never appear in scripts, docs, or configuration.

## Mount and persistence

For local development, bind-mount the repository at `/workspace` and set the working directory there:

```bash
docker run --rm -it \
  --platform linux/amd64 \
  -v "$(pwd):/workspace" \
  -w /workspace \
  jev-ci:phase1
```

- **Source and scripts** live in the mounted checkout and update live as the host edits files.
- **Generated data** under `data/`, `cache/`, and `results/` is written into the mount, so it survives container restarts and image rebuilds.
- **Defects4J** is not mounted; it comes only from the image at `/opt/defects4j`.

Copying the tree into the image instead of mounting is allowed for one-shot CI-style runs, but development and Phase 2+ work assume the bind mount above so outputs remain on the host.

### Writable output directories

These paths must be writable by the process that runs experiment scripts:

| Host path | Container path |
| --- | --- |
| `./data` | `/workspace/data` |
| `./cache` | `/workspace/cache` |
| `./results` | `/workspace/results` |

The repository tracks empty placeholders (`.gitkeep`) so the directories exist for bind mounts. With the default image user, writes go to the mounted host tree. Prefer writing only under these directories (and other paths inside `/workspace`), never under `/opt/defects4j`.

### Credentials (later phases)

Phase 1 builds and smoke checks require **no** API keys.

For later paid calls (embeddings, Jev, GPT), inject credentials at **runtime** only:

```bash
# Option A: env file (recommended). Start from .env.example; never commit .env.
docker run --rm --platform linux/amd64 \
  --env-file .env \
  -v "$(pwd):/workspace" \
  -w /workspace \
  jev-ci:phase1 \
  python scripts/run_jev.py

# Option B: explicit flags
docker run --rm --platform linux/amd64 \
  -e OPENAI_API_KEY \
  -e TYPESAFE_API_KEY \
  -v "$(pwd):/workspace" \
  -w /workspace \
  jev-ci:phase1 \
  python scripts/run_jev.py
```

Do not `COPY` `.env`, API keys, or result/cache trees into the image. `.dockerignore` excludes them from build context; `.gitignore` keeps `.env` and `cache/` out of git while leaving `data/manifest.json`, `EXPERIMENT.md`, and deliberate `results/` artifacts trackable.

## Environment variables

Every interactive shell and noninteractive script in the container inherits at least:

| Variable | Value | Purpose |
| --- | --- | --- |
| `TZ` | `America/Los_Angeles` | Defects4J-required timezone for reproducible test behavior |
| `JAVA_HOME` | Java 11 JDK path (set in the image) | Pin the runtime Defects4J expects |
| `PATH` | includes `/opt/defects4j/framework/bin` and `$JAVA_HOME/bin` | Make `defects4j`, `java`, and `javac` available without shell profile tricks |
| `D4J_HOME` | `/opt/defects4j` | Single canonical Defects4J root for scripts and docs |

A later `defects4j` subprocess must see this environment without depending on the developer's host shell.

## Working directory and invocation

- Default `WORKDIR` and run `-w` are `/workspace`.
- Run project scripts from `/workspace` using the conventions in [python.md](python.md), for example:

```bash
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" \
  -w /workspace \
  jev-ci:phase1 \
  python scripts/check_environment.py
```

- Invoke Defects4J as `defects4j ...` (via `PATH`), never via a host-relative path.

## CPU architecture

Build and run with a fixed platform:

```text
linux/amd64
```

Defects4J and its Java toolchain are validated primarily on x86_64 Linux. Pinning `linux/amd64` keeps results comparable on Intel/AMD hosts and on Apple Silicon (via emulation). Pass `--platform linux/amd64` to `docker build` and `docker run`; do not rely on the host's native architecture default.
