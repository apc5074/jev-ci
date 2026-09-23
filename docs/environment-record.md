# Environment record schema

Produced by `scripts/check_environment.py` at `results/environment.json`.

## Run

```bash
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" \
  -w /workspace \
  jev-ci:phase1 \
  python scripts/check_environment.py
```

Exit `0` only when every check passes and the JSON file is written. Failures print `error: …` to stderr and exit nonzero. The script does not read credentials or dump the full process environment.

## Checks

| Check | Rule |
| --- | --- |
| Python | Running interpreter is 3.12.x |
| Timezone | `TZ` equals `America/Los_Angeles` |
| Java | `JAVA_HOME` exists; `java -version` reports 11.x |
| Executables | `git`, `svn`, `perl`, `cpanm`, `java`, `javac`, `defects4j` on `PATH` |
| Defects4J pin | Checkout at `D4J_HOME` matches `config/defects4j.pin` (`D4J_COMMIT`) |
| Defects4J version | README header declares `D4J_VERSION` from the pin |
| Smoke | `defects4j info -p Lang` exits 0 |

Bug-list / manifest validation is intentionally out of scope (Phase 2).

## Schema

JSON object. Keys are stable; `checked_at` and `repository_commit` are the only fields expected to vary across successful re-runs on the same image.

| Field | Type | Meaning |
| --- | --- | --- |
| `checked_at` | string | UTC ISO-8601 time the check ran |
| `defects4j_version` | string | Release label from the pin (e.g. `3.0.1`) |
| `defects4j_commit` | string | Full Git SHA of `/opt/defects4j` |
| `python_version` | string | e.g. `3.12.14` |
| `java_version` | string | Parsed from `java -version`, e.g. `11.0.32.1` |
| `os` | string | Pretty OS name when available |
| `architecture` | string | `platform.machine()`, e.g. `x86_64` |
| `timezone` | string | Value of `TZ` |
| `repository_commit` | string or `null` | jev-ci `/workspace` HEAD when `.git` is usable; **`null` if unavailable** (never `""`) |
| `d4j_home` | string | Defects4J root |
| `java_home` | string or `null` | `JAVA_HOME` |
| `executables` | object | Map of required command name → absolute path |

Example:

```json
{
  "architecture": "x86_64",
  "checked_at": "2026-09-22T23:00:00+00:00",
  "d4j_home": "/opt/defects4j",
  "defects4j_commit": "6d54320e0db5a357f9ab38a8e4d2e5aead7e1c09",
  "defects4j_version": "3.0.1",
  "executables": {
    "cpanm": "/usr/bin/cpanm",
    "defects4j": "/opt/defects4j/framework/bin/defects4j",
    "git": "/usr/bin/git",
    "java": "/usr/lib/jvm/java-11-openjdk-amd64/bin/java",
    "javac": "/usr/lib/jvm/java-11-openjdk-amd64/bin/javac",
    "perl": "/usr/bin/perl",
    "svn": "/usr/bin/svn"
  },
  "java_home": "/usr/lib/jvm/java-11-openjdk-amd64",
  "java_version": "11.0.32.1",
  "os": "Ubuntu 22.04.5 LTS",
  "python_version": "3.12.14",
  "repository_commit": null,
  "timezone": "America/Los_Angeles"
}
```
