# Python conventions

How to run experiment Python inside the container. Paths and mounts are defined in [environment.md](environment.md).

## Interpreter

Inside `jev-ci:phase1`:

| Command | Meaning |
| --- | --- |
| `python` | Canonical interpreter (Python 3.12) |
| `python3` | Same as `python` |
| `python -m pip …` | Install or inspect packages |

Do not use host Python for experiment scripts.

## Dependencies

Declared in the repository root `requirements.txt` and installed at image build time:

```bash
python -m pip install --no-cache-dir -r requirements.txt
```

Phase 1 ships a comments-only `requirements.txt` (stdlib only). Later phases pin third-party packages in that file and rebuild the image.

## Container invocation

From the repository root on the host:

```bash
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" \
  -w /workspace \
  jev-ci:phase1 \
  python path/to/script.py [args...]
```

Equivalent forms:

```bash
# module form once packages exist under src/
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" \
  -w /workspace \
  jev-ci:phase1 \
  python -m package.module

# interactive shell with the same environment
docker run --rm -it --platform linux/amd64 \
  -v "$(pwd):/workspace" \
  -w /workspace \
  jev-ci:phase1 \
  bash
```

A script started this way inherits image `ENV` values, including `TZ=America/Los_Angeles`, `JAVA_HOME`, `D4J_HOME`, and a `PATH` that contains `/opt/defects4j/framework/bin`. Do not re-export those from the host shell unless deliberately overriding for a local debug session.

## Noninteractive script rules

Scripts under `scripts/` and `src/` must be safe to run noninteractively in CI and in one-shot containers:

1. **Exit codes:** exit `0` only on success; use a nonzero status for any failed check or unrecoverable error.
2. **Errors:** print a specific message to stderr before exiting nonzero. Avoid bare stack traces as the only signal when a prerequisite is missing.
3. **Environment:** read `TZ`, `JAVA_HOME`, `D4J_HOME`, and `PATH` from the process environment. Do not assume a developer interactive profile, host home directory, or macOS/Windows paths.
4. **Working directory:** assume cwd is `/workspace` unless the script documents otherwise.
5. **No prompts:** never wait for stdin; take options from argv or environment variables.
6. **Determinism:** prefer explicit pins and recorded inputs; do not silently depend on floating network content except where a ticket documents a download step.
