# Phase 1 tickets — Reproducible experiment environment

**Phase goal:** A new agent can build a Linux container, run Defects4J 3.0.1 with the required Java and timezone settings, record the environment, and hand a working container to Phase 2. This phase sets up infrastructure; it does not select bugs, check out examples, call model APIs, or implement the experiment.

**Source of truth:** [../overall.md](../overall.md), especially sections 2, 6, 7, and 44, and [../phases.md](../phases.md), Phase 1. If installation details differ from the outline, record the reason and the working commands. Preserve the required version and environment settings.

Tickets are ordered by dependency. Each ticket should be independently reviewable. File names below are intended outputs; an agent may make a small, documented adjustment when the working implementation requires it.

## P1-01 — Define the container and workspace contract ✅ COMPLETE

**Depends on:** Nothing.

**Status:** Complete. Contract documented in [`docs/environment.md`](../../docs/environment.md).

**Work**

- Choose and document fixed in-container paths for the Defects4J installation, the repository checkout, and writable experiment data/cache directories. Keep the Defects4J installation separate from project-generated artifacts.
- Decide how the local repository is mounted or copied for development and how generated data persists across container restarts. Document the working directory and the invocation pattern later scripts will use.
- Define environment variables needed by later phases: at minimum `TZ=America/Los_Angeles`, a Java 11 runtime, and a `PATH` containing `framework/bin` from the installed Defects4J checkout. Use one canonical Defects4J path throughout scripts and docs.
- Decide how the image runs on machines with different CPU architectures. If a fixed platform is necessary for Java/Defects4J compatibility, make it explicit in the build and run instructions.

**Deliverable:** A short path and environment contract in `README.md` or a focused setup document. Use the same choices in all subsequent tickets.

**Acceptance:** A reviewer can identify where Defects4J, the working repository, persistent data, and caches live, and what environment a later `defects4j` subprocess inherits. No path relies on the developer's home directory.

## P1-02 — Pin the base toolchain and build the Docker image ✅ COMPLETE

**Depends on:** P1-01.

**Status:** Complete. Image `jev-ci:phase1` builds from the root `Dockerfile`; pins and verification are in [`docs/toolchain.md`](../../docs/toolchain.md).

**Work**

- Create a `Dockerfile` using Ubuntu 22.04. Install Python 3.12, Java 11, Git, Subversion, Perl, cpanm, timezone data, and the OS tools actually needed by Defects4J setup. Ubuntu 22.04's default Python is not 3.12, so use an explicit, reproducible Python 3.12 installation method.
- Set `TZ=America/Los_Angeles`, `JAVA_HOME` for Java 11, and noninteractive package installation where appropriate. Ensure `python3`/the documented Python command invokes Python 3.12 inside the image.
- Pin the base image and non-default external toolchain sources enough that the build is reproducible; document the exact versions or immutable references used. Avoid relying on a floating `latest` image or an unrecorded package repository.
- Keep build layers and image contents focused on dependencies needed for this experiment. Do not copy API keys or local result directories into the image.

**Deliverables:** `Dockerfile` and any narrowly scoped toolchain setup file it needs.

**Acceptance:** A clean image build succeeds, and a container reports Ubuntu 22.04, Python 3.12, Java 11, the Los Angeles timezone, and callable `git`, `svn`, `perl`, and `cpanm` commands. Capture the exact verification commands in the setup docs.

## P1-03 — Install and initialize the pinned Defects4J release ✅ COMPLETE

**Depends on:** P1-02.

**Status:** Complete. Defects4J 3.0.1 at commit `6d54320e0db5a357f9ab38a8e4d2e5aead7e1c09` is installed in the image via `scripts/install_defects4j.sh` and `config/defects4j.pin`. `defects4j info -p Lang` succeeds in a fresh container.

**Work**

- Resolve Defects4J release `3.0.1` to an immutable Git commit, then clone/check out that commit in the container. Record both the release label and commit SHA.
- From that checkout, run the documented `cpanm --installdeps .` and `./init.sh` sequence. Account for network access and build time in the container workflow. Fail the build or setup clearly if a dependency or project repository cannot be initialized.
- Put the checkout's `framework/bin` on `PATH` for interactive shells and noninteractive scripts. Avoid an install that works only because of a developer's shell configuration.
- Verify the release actually installed is 3.0.1 using available release metadata; record the evidence used if the CLI does not expose a version command.

**Deliverables:** Reproducible Defects4J installation steps in the Dockerfile or a versioned bootstrap script, plus a pinned commit reference in a tracked configuration/documentation file.

**Acceptance:** From a newly created container, `defects4j info -p Lang` exits successfully and displays project information. The installed Defects4J checkout is at the recorded commit. No host installation of Defects4J is required.

## P1-04 — Establish Python dependency and command conventions ✅ COMPLETE

**Depends on:** P1-02; can be developed while P1-03 is running.

**Status:** Complete. Root `requirements.txt` is installed in the image; conventions are in [`docs/python.md`](../../docs/python.md).

**Work**

- Create `requirements.txt` for Python dependencies actually required at this stage and pin any third-party packages. A comments-only file is acceptable if Phase 1 needs only the standard library; later phases will add their dependencies deliberately.
- Install that file with Python 3.12 in the image. Document the command that later agents should use to run Python modules and scripts inside the container.
- Define a simple convention for reproducible, noninteractive scripts: explicit exit codes, useful error messages, and no implicit dependence on the current host shell's environment.

**Deliverables:** `requirements.txt`, Dockerfile installation step, and documented Python invocation convention.

**Acceptance:** A clean image build installs the declared Python environment, `python` or the documented command resolves to Python 3.12, and a script launched through the documented container command inherits the required Java, timezone, and Defects4J settings.

## P1-05 — Separate durable outputs from image content and secrets ✅ COMPLETE

**Depends on:** P1-01 and P1-02.

**Status:** Complete. `.dockerignore`, `.gitignore`, `.env.example`, and mount/credential docs in [`docs/environment.md`](../../docs/environment.md).

**Work**

- Add `.dockerignore` so builds do not send local caches, generated data, result files, credentials, or large Defects4J checkouts as context.
- Add `.gitignore` rules for generated checkouts, caches, temporary files, local environment files, and credentials while leaving intentional tracked artifacts such as the future manifest and experiment outputs trackable. Make ignore rules specific enough not to hide `data/manifest.json`, `EXPERIMENT.md`, or later results by accident.
- Document how to mount persistent project data/cache directories and how API credentials will be injected at runtime in later phases. Phase 1 needs no API key and must not require one to build or validate the image.
- Make the working paths writable by the user/process that runs experiment scripts, including when the repository is bind-mounted.

**Deliverables:** `.dockerignore`, `.gitignore`, documented mount and credential conventions.

**Acceptance:** Rebuilding the image does not include local secrets or generated artifacts, a container restart preserves mounted work, and a container process can write a small file to each documented output directory.

## P1-06 — Add an environment record and smoke check ✅ COMPLETE

**Depends on:** P1-03 and P1-04.

**Status:** Complete. `scripts/check_environment.py` writes `results/environment.json`; schema in [`docs/environment-record.md`](../../docs/environment-record.md).

**Work**

- Add a small, noninteractive check script, for example `scripts/check_environment.py`, that verifies Python 3.12, Java 11, `TZ=America/Los_Angeles`, the required executables, the pinned Defects4J commit, and successful `defects4j info -p Lang` output.
- Produce a machine-readable environment record, for example `results/environment.json`, containing Defects4J version and commit, Python version, Java version, OS, architecture, timezone, and the time the check ran. Include the repository commit when available; distinguish an unavailable commit from an empty value. Do not include credentials or the full process environment.
- Ensure checks fail with a nonzero exit code and a specific message when a prerequisite is wrong. Make repeated runs safe and deterministic except for deliberately recorded observation fields such as time.
- Keep this check limited to toolchain/Defects4J availability. Phase 2 owns bug-list validation.

**Deliverables:** Environment check/record script and its documented output schema.

**Acceptance:** The script passes in the clean container and writes a readable record. A deliberately wrong Java version, timezone, or unavailable `defects4j` command causes a clear failure. Its recorded Defects4J commit matches the installation pin.

## P1-07 — Document and exercise the clean setup path ✅ COMPLETE

**Depends on:** P1-01 through P1-06.

**Status:** Complete. Setup in [`docs/setup.md`](../../docs/setup.md) / [`README.md`](../../README.md); verification record in [`docs/verification-phase1.md`](../../docs/verification-phase1.md).

**Work**

- Write the exact build, run, mount, and smoke-check commands in `README.md` or a focused `docs/setup.md`. State expected build time/network requirements for the Defects4J initialization and how to resume or diagnose a failed setup.
- Execute those commands from a fresh image/container state, not from a container previously prepared by hand. Verify the documented command works without relying on host Java, Python, Perl, or Defects4J.
- Check that the recorded environment is accessible to Phase 2, that output paths are writable, and that the repo itself is reachable from inside the container.
- Record the observed versions and any setup caveats. Keep setup documentation concise enough that another agent can follow it without reading Docker internals.

**Deliverables:** Setup instructions and a short verification record with the commands run and their results.

**Acceptance:** A new agent following only the setup instructions can build the image, start the container, run the environment check, and see `defects4j info -p Lang` succeed. All seven tickets are complete; Phase 2 can start without additional environment design.

## Phase completion gate ✅

Phase 1 is implemented when the Docker image builds from a clean checkout, the pinned Defects4J 3.0.1 installation works in it, the environment record captures the required metadata, output directories are writable and persistent as documented, and the smoke check passes using only the documented commands. The handoff to Phase 2 is the container invocation, pinned Defects4J commit, path contract, and environment record.
