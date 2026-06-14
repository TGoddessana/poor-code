#!/usr/bin/env bash
# Full-15 regression after the non-destructive + anti-fabrication verifier fix (main @ 5df583f).
# Dump on so each task keeps its verifier:verdict trace for classification.
set -uo pipefail
export DOCKER_HOST="unix:///Users/goddessana/.docker/run/docker.sock"
export PYTHONPATH="."
export POOR_CODE_PROVIDER="ollama_cloud"
export POOR_CODE_MODEL="gemma4:31b-cloud"
export POOR_CODE_GIT_REF="main"
export POOR_CODE_ADVISORY_GATES="1"
export POOR_CODE_DUMP_PROMPTS="/logs/poorcode-dump.txt"
export OLLAMA_API_KEY="$(python3 -c "import json,os;print(json.load(open(os.path.expanduser('~/.poor-code/auth.json')))['providers']['ollama_cloud']['api_key'])")"
echo "Full-15 post-fix regression (gemma4:31b-cloud, ref=main)"
tb run --agent-import-path bench.poor_code_agent:PoorCodeAgent \
  --dataset terminal-bench-core==0.1.1 --global-agent-timeout-sec 3600 \
  -t csv-to-parquet -t simple-web-scraper -t organization-json-generator \
  -t password-recovery -t fix-git -t grid-pattern-transform -t fibonacci-server \
  -t openssl-selfsigned-cert -t nginx-request-logging -t count-dataset-tokens \
  -t heterogeneous-dates -t sqlite-db-truncate -t fix-permissions \
  -t write-compressor -t create-bucket \
  --n-concurrent 4 --no-livestream
echo "TB_EXIT=$?"
