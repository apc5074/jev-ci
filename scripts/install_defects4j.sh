#!/usr/bin/env bash
# Install and initialize the pinned Defects4J release into D4J_HOME.
# Intended to run during the image build; fails loudly on any error.
set -euo pipefail

PIN_FILE="${1:-/tmp/defects4j.pin}"
D4J_HOME="${D4J_HOME:-/opt/defects4j}"

if [[ ! -f "$PIN_FILE" ]]; then
  echo "error: pin file not found: $PIN_FILE" >&2
  exit 1
fi

# shellcheck disable=SC1090
source "$PIN_FILE"

: "${D4J_VERSION:?missing D4J_VERSION in pin file}"
: "${D4J_COMMIT:?missing D4J_COMMIT in pin file}"
: "${D4J_REPO:?missing D4J_REPO in pin file}"

echo "Installing Defects4J ${D4J_VERSION} at ${D4J_COMMIT} into ${D4J_HOME}"

rm -rf "$D4J_HOME"
git clone "$D4J_REPO" "$D4J_HOME"
git -C "$D4J_HOME" checkout --detach "$D4J_COMMIT"

installed_commit="$(git -C "$D4J_HOME" rev-parse HEAD)"
if [[ "$installed_commit" != "$D4J_COMMIT" ]]; then
  echo "error: expected commit ${D4J_COMMIT}, got ${installed_commit}" >&2
  exit 1
fi

# Release label evidence: README header is "Defects4J -- version X.Y.Z"
if ! grep -Eq "^Defects4J -- version ${D4J_VERSION}([[:space:]]|$)" "$D4J_HOME/README.md"; then
  echo "error: README.md does not declare version ${D4J_VERSION}" >&2
  head -n 3 "$D4J_HOME/README.md" >&2 || true
  exit 1
fi

cd "$D4J_HOME"
cpanm --notest --installdeps .
./init.sh

# Persist pin alongside the checkout for later environment checks.
cp "$PIN_FILE" "$D4J_HOME/defects4j.pin"

echo "Defects4J ${D4J_VERSION} initialized at ${installed_commit}"
