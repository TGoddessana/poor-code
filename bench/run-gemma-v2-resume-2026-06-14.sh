#!/usr/bin/env bash
# Resume after reboot: the 11 tasks not finished in run 2026-06-14__01-40-41.
set -uo pipefail
export DOCKER_HOST="unix:///Users/goddessana/.docker/run/docker.sock"
export PYTHONPATH="."
export POOR_CODE_PROVIDER="ollama_cloud"
export POOR_CODE_MODEL="gemma4:31b-cloud"
export POOR_CODE_GIT_REF="feat/verification-agent"
export POOR_CODE_ADVISORY_GATES="1"
export OLLAMA_API_KEY="$(python3 -c "import json,os;print(json.load(open(os.path.expanduser('~/.poor-code/auth.json')))['providers']['ollama_cloud']['api_key'])")"
echo "Resuming v2+leniency run (gemma, 11 remaining tasks)"
tb run --agent-import-path bench.poor_code_agent:PoorCodeAgent \
  --dataset terminal-bench-core==0.1.1 --global-agent-timeout-sec 3600 \
  -t csv-to-parquet -t simple-web-scraper -t password-recovery -t fix-git \
  -t fibonacci-server -t openssl-selfsigned-cert -t count-dataset-tokens \
  -t heterogeneous-dates -t sqlite-db-truncate -t write-compressor -t create-bucket \
  --n-concurrent 4 --no-livestream
echo "TB_EXIT=$?"
