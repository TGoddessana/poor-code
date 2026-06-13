#!/usr/bin/env bash
# Verification v2 bench: gemma4:31b-cloud, 10 tasks, on feat/verification-agent
# (observe-judge Verifier replaces the bash-check floor; criteria-only oracle; advisory
# gates on; env noise dropped). Watch genuine_done — does the verifier track truth?
set -uo pipefail

export DOCKER_HOST="unix:///Users/goddessana/.docker/run/docker.sock"
export PYTHONPATH="."
export POOR_CODE_PROVIDER="ollama_cloud"
export POOR_CODE_MODEL="gemma4:31b-cloud"
export POOR_CODE_GIT_REF="feat/verification-agent"
export POOR_CODE_ADVISORY_GATES="1"
export OLLAMA_API_KEY="$(python3 -c "import json,os;print(json.load(open(os.path.expanduser('~/.poor-code/auth.json')))['providers']['ollama_cloud']['api_key'])")"

echo "Starting verification-v2 run (gemma4:31b-cloud, 10 tasks, ref=${POOR_CODE_GIT_REF})"
tb run --agent-import-path bench.poor_code_agent:PoorCodeAgent \
  --dataset terminal-bench-core==0.1.1 --global-agent-timeout-sec 3600 \
  -t grid-pattern-transform -t simple-web-scraper -t openssl-selfsigned-cert \
  -t organization-json-generator -t hello-world -t password-recovery \
  -t fix-git -t csv-to-parquet -t swe-bench-langcodes -t fibonacci-server \
  --n-concurrent 4 --no-livestream
echo "TB_EXIT=$?"
