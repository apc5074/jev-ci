# Toolchain pins (Phase 1)

Sources and verification for the container image defined by the root `Dockerfile`. Path and mount rules remain in [environment.md](environment.md).

## Pinned references

| Component | Pin | Notes |
| --- | --- | --- |
| Base image | `ubuntu:22.04@sha256:b8b6ee6aa931ecd9d0d952abc34dc0e5f7c6a30c6bb71b079fe399fde0329c02` | Ubuntu 22.04.5 LTS (jammy), `linux/amd64` |
| Platform | `linux/amd64` | Required on build and run; see environment contract |
| Timezone | `TZ=America/Los_Angeles` | Set in the image |
| Java | OpenJDK 11 (`openjdk-11-jdk-headless`) | `JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64` |
| Python | CPython 3.12 from [deadsnakes](https://launchpad.net/~deadsnakes/+archive/ubuntu/ppa) | `python` and `python3` point at 3.12 |
| pip | Bootstrapped via `https://bootstrap.pypa.io/get-pip.py` at image build | Used by later phases to install `requirements.txt` |
| Defects4J | Release `3.0.1` at commit `6d54320e0db5a357f9ab38a8e4d2e5aead7e1c09` (`v3.0.1`) | Installed at `/opt/defects4j` during image build; pin in `config/defects4j.pin` |

OS packages from Ubuntu archives (`git`, `subversion`, `perl`, `cpanminus`, `tzdata`, build tools) are installed at image build time from the jammy repositories. Rebuilds may pick newer package revisions within those archives; the base image digest and Python major/minor (3.12) are the hard pins for this phase.

## Build

From the repository root:

```bash
docker build --platform linux/amd64 -t jev-ci:phase1 .
```

Expected: the build completes without copying API keys, host caches, or result directories into the image. Copied build inputs are `config/defects4j.pin`, `scripts/install_defects4j.sh`, and `requirements.txt`.

Build note: Defects4J `./init.sh` downloads project repositories and tool JARs; expect several minutes of network activity on first build.

## Verification

### Toolchain (P1-02)

Run a one-shot check container:

```bash
docker run --rm --platform linux/amd64 jev-ci:phase1 bash -lc '
  set -euo pipefail
  . /etc/os-release
  test "$VERSION_ID" = "22.04"
  python --version
  python3 --version
  java -version
  echo "TZ=$TZ"
  date
  command -v git && git --version
  command -v svn && svn --version --quiet
  command -v perl && perl -v | head -n 2
  command -v cpanm && cpanm --version
  test -n "$JAVA_HOME" && test -d "$JAVA_HOME"
  test "$D4J_HOME" = "/opt/defects4j"
'
```

Acceptance expectations:

- OS reports Ubuntu 22.04
- `python` / `python3` report Python 3.12.x
- `java -version` reports OpenJDK 11
- `TZ` is `America/Los_Angeles` and `date` reflects that zone
- `git`, `svn`, `perl`, and `cpanm` are callable

### Defects4J (P1-03)

```bash
docker run --rm --platform linux/amd64 jev-ci:phase1 bash -lc '
  set -euo pipefail
  test "$(git -C "$D4J_HOME" rev-parse HEAD)" = "6d54320e0db5a357f9ab38a8e4d2e5aead7e1c09"
  grep -Eq "^Defects4J -- version 3.0.1" "$D4J_HOME/README.md"
  defects4j info -p Lang
'
```

Acceptance expectations:

- Checkout commit matches `config/defects4j.pin`
- README header declares version `3.0.1` (CLI has no dedicated version command)
- `defects4j info -p Lang` exits 0 and prints Lang project information

### Observed versions (P1-02 verification)

Captured from `jev-ci:phase1` on 2026-09-22 after a clean `linux/amd64` build:

| Check | Result |
| --- | --- |
| OS | Ubuntu 22.04 |
| `python` / `python3` | Python 3.12.14 |
| `java` | OpenJDK 11.0.32.1 |
| `TZ` / `date` | `America/Los_Angeles` (PDT) |
| `git` | 2.34.1 |
| `svn` | 1.14.1 |
| `perl` | 5.34.0 |
| `cpanm` | App::cpanminus 1.7045 |
| `JAVA_HOME` | `/usr/lib/jvm/java-11-openjdk-amd64` |
| `D4J_HOME` | `/opt/defects4j` |

### Observed Defects4J (P1-03 verification)

| Check | Result |
| --- | --- |
| Release | 3.0.1 (README header + tag `v3.0.1`) |
| Commit | `6d54320e0db5a357f9ab38a8e4d2e5aead7e1c09` |
| `defects4j info -p Lang` | Succeeds in a fresh container |

### Python conventions (P1-04)

Documented in [python.md](python.md). Image installs root `requirements.txt` (Phase 1: stdlib only). Canonical run:

```bash
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" \
  -w /workspace \
  jev-ci:phase1 \
  python path/to/script.py
```

Verified: `python` is 3.12.14 and a one-shot container script inherits `TZ`, `JAVA_HOME`, `D4J_HOME`, and `defects4j` on `PATH`.

### Environment smoke check (P1-06)

See [environment-record.md](environment-record.md).

```bash
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" \
  -w /workspace \
  jev-ci:phase1 \
  python scripts/check_environment.py
```

Verified: writes `results/environment.json` with Defects4J commit `6d54320e0db5a357f9ab38a8e4d2e5aead7e1c09`; wrong `TZ`, missing `defects4j`, or Java 17 each fail with a clear stderr message.
