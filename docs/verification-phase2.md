# Phase 2 verification record

Locked the deterministic Defects4J dataset split on 2026-09-22 using only the Phase 1 container and the commands below.

## Commands

```bash
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 \
  python scripts/check_environment.py

docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 \
  python src/select_bugs.py create

docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 \
  python src/select_bugs.py verify
```

`verify` left `data/manifest.json` byte-for-byte unchanged
(SHA-256 `ec8b1dbc570ea8fa0a160fc5fe1de55d821c91f1452979c544af5094a4582971` before and after).

## Provenance

| Field | Value |
| --- | --- |
| Defects4J | 3.0.1 @ `6d54320e0db5a357f9ab38a8e4d2e5aead7e1c09` |
| Selection seed | `20260922` |
| Manifest `created_at` | `2026-09-22T23:16:15+00:00` |
| `git_commit` at generation | `784d3d84dd09ae7f53cb828eac65532370906c56` (repo HEAD before the lock commit) |
| Lock commit (this tree) | `51abb043fb445cfe13e293d01468bbd7c58ac0b9` |

## Active-set counts

| Project | Active | Selected | Development | Evaluation |
| --- | ---: | ---: | ---: | ---: |
| Cli | 39 | 30 | 5 | 25 |
| Lang | 61 | 30 | 5 | 25 |
| Math | 106 | 30 | 5 | 25 |
| Jsoup | 93 | 30 | 5 | 25 |
| JacksonDatabind | 110 | 30 | 5 | 25 |
| **Total** | — | **150** | **25** | **125** |

No ID appears in both splits. Every project contributes exactly 30 selected bugs.

## Development IDs (25)

```text
Cli-30 Cli-15 Cli-39 Cli-1 Cli-7
Lang-9 Lang-27 Lang-3 Lang-15 Lang-35
Math-25 Math-7 Math-87 Math-27 Math-100
Jsoup-2 Jsoup-51 Jsoup-29 Jsoup-70 Jsoup-4
JacksonDatabind-56 JacksonDatabind-95 JacksonDatabind-12 JacksonDatabind-105 JacksonDatabind-28
```

Full ordered selections (including evaluation) are in `data/manifest.json` under `projects.*.selected_qualified_ids`.

## Re-check

```bash
python src/select_bugs.py verify
python -m unittest discover -s tests -v
```
