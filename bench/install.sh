#!/usr/bin/env bash
# Install poor-code into a fresh Debian task container for terminal-bench.
# Assumes only the base OS; installs Python tooling then poor-code.
set -euo pipefail

apt-get update -y
apt-get install -y --no-install-recommends python3 python3-pip git

# Install uv (fast installer) then poor-code from source mounted/copied at /agent.
pip3 install --no-cache-dir uv || true

# The harness copies the agent's source tree to the container; install from there.
# Adjust the path if the harness mounts it elsewhere.
if [ -d /agent ]; then
    pip3 install --no-cache-dir /agent
else
    pip3 install --no-cache-dir poor-code || \
        echo "WARNING: poor-code source not found at /agent and not on PyPI"
fi

command -v poor-code >/dev/null 2>&1 || echo "WARNING: poor-code not on PATH after install"
