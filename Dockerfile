# syntax=docker/dockerfile:1.7

# Pinned Ubuntu 22.04 (jammy). Digest recorded in docs/toolchain.md.
FROM --platform=linux/amd64 ubuntu:22.04@sha256:b8b6ee6aa931ecd9d0d952abc34dc0e5f7c6a30c6bb71b079fe399fde0329c02

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=America/Los_Angeles \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    D4J_HOME=/opt/defects4j \
    JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64

# Make tzdata configure noninteractively.
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Base OS tools required by Defects4J setup and the experiment toolchain.
# Python 3.12 comes from the deadsnakes PPA (Ubuntu 22.04 ships 3.10 by default).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        wget \
        gnupg \
        software-properties-common \
        tzdata \
        git \
        subversion \
        perl \
        cpanminus \
        build-essential \
        unzip \
        openjdk-11-jdk-headless \
    && add-apt-repository -y ppa:deadsnakes/ppa \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        python3.12 \
        python3.12-venv \
        python3.12-dev \
    && rm -rf /var/lib/apt/lists/*

# Canonical Python commands for this experiment are python / python3 → 3.12.
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1 \
    && update-alternatives --install /usr/bin/python python /usr/bin/python3.12 1

# Bootstrap pip for Python 3.12 without relying on the distro python3-pip package.
RUN curl -fsSL https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py \
    && python3.12 /tmp/get-pip.py --no-cache-dir \
    && rm /tmp/get-pip.py

ENV PATH="${D4J_HOME}/framework/bin:${JAVA_HOME}/bin:/usr/local/bin:${PATH}"

# Install pinned Defects4J 3.0.1 (see config/defects4j.pin). Network + long init required.
COPY config/defects4j.pin /tmp/defects4j.pin
COPY scripts/install_defects4j.sh /tmp/install_defects4j.sh
RUN chmod +x /tmp/install_defects4j.sh \
    && /tmp/install_defects4j.sh /tmp/defects4j.pin \
    && rm -f /tmp/install_defects4j.sh \
    && defects4j info -p Lang >/dev/null

# Python dependencies (Phase 1: stdlib-only requirements.txt; see docs/python.md).
COPY requirements.txt /tmp/requirements.txt
RUN python -m pip install --no-cache-dir -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

WORKDIR /workspace

# Placeholder directories matching docs/environment.md. Bind mounts replace these at run time.
RUN mkdir -p /workspace/data /workspace/cache /workspace/results

CMD ["bash"]
