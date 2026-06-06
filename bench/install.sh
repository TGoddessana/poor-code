#!/usr/bin/env bash
# Install poor-code into a fresh Debian task container for terminal-bench.
# Assumes only the base OS; installs Python tooling then poor-code.
set -euo pipefail

apt-get update -y
# curl + ca-certificates are NOT guaranteed on the base (e.g. Ubuntu noble lacks
# curl), and the uv bootstrap below needs them for the fallback path.
apt-get install -y --no-install-recommends python3 python3-pip git curl ca-certificates

# Install uv. The bench base image ships Python 3.13, but poor-code needs >=3.14,
# so we install into a uv-managed 3.14 rather than the system interpreter.
# --break-system-packages: PEP 668 marks the system env externally-managed on
# bookworm/noble, so a bare `pip3 install` is refused. curl is the fallback.
pip3 install --no-cache-dir --break-system-packages uv \
    || (curl -LsSf https://astral.sh/uv/install.sh | sh)
export PATH="/root/.local/bin:${PATH}"
# Entry-point scripts (the `poor-code` console script) land here, which is on PATH.
export UV_TOOL_BIN_DIR=/usr/local/bin

# Delivery order: a locally-mounted source tree at /agent (if a harness provides
# one) wins; otherwise install from the pushed git branch.
# POOR_CODE_GIT_REF overrides the branch/tag/commit benched (default below).
POOR_CODE_GIT_URL="${POOR_CODE_GIT_URL:-https://github.com/TGoddessana/poor-code}"
POOR_CODE_GIT_REF="${POOR_CODE_GIT_REF:-main}"

if [ -d /agent ]; then
    uv tool install --python 3.14 --from /agent poor-code
else
    uv tool install --python 3.14 "git+${POOR_CODE_GIT_URL}@${POOR_CODE_GIT_REF}" || \
        echo "WARNING: could not install poor-code from git ($POOR_CODE_GIT_REF)"
fi

command -v poor-code >/dev/null 2>&1 || echo "WARNING: poor-code not on PATH after install"
