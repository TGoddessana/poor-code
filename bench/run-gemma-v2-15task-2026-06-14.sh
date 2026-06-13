#!/usr/bin/env bash
# Verification v2 + leniency guard: gemma4:31b-cloud, 15 mid-difficulty tasks,
# feat/verification-agent (commit dac0781). Watch whether the leniency guard drops
# false_accept while keeping false_abandon=0.
set -uo pipefail

export DOCKER_HOST="unix:///Users/goddessana/.docker/run/docker.sock"
export PYTHONPATH="."
export POOR_CODE_PROVIDER="ollama_cloud"
export POOR_CODE_MODEL="gemma4:31b-cloud"
export POOR_CODE_GIT_REF="feat/verification-agent"
export POOR_CODE_ADVISORY_GATES="1"
export OLLAMA_API_KEY="$(python3 -c "import json,os;print(json.load(open(os.path.expanduser('~/.poor-code/auth.json')))['providers']['ollama_cloud']['api_key'])")"

echo "Starting v2+leniency run (gemma4:31b-cloud, 15 tasks, ref=${POOR_CODE_GIT_REF})"
tb run --agent-import-path bench.poor_code_agent:PoorCodeAgent \
  --dataset terminal-bench-core==0.1.1 --global-agent-timeout-sec 3600 \
  -t csv-to-parquet -t simple-web-scraper -t organization-json-generator \
  -t password-recovery -t fix-git -t grid-pattern-transform -t fibonacci-server \
  -t openssl-selfsigned-cert -t nginx-request-logging -t count-dataset-tokens \
  -t heterogeneous-dates -t sqlite-db-truncate -t fix-permissions \
  -t write-compressor -t create-bucket \
  --n-concurrent 4 --no-livestream
echo "TB_EXIT=$?"
