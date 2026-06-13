#!/usr/bin/env bash
# 10-task terminal-bench run for poor-code with gpt-5.4-nano (OpenAI provider).
# Code under test = GitHub main (install.sh installs git+...@main inside container).
set -uo pipefail

export DOCKER_HOST="unix:///Users/goddessana/.docker/run/docker.sock"
export PYTHONPATH="."
export POOR_CODE_PROVIDER="openai"
export POOR_CODE_MODEL="gpt-5.4-nano"
# Pull the OpenAI key from ~/.poor-code/auth.json (avoids hardcoding the secret).
export OPENAI_API_KEY="$(python3 -c "import json,os;print(json.load(open(os.path.expanduser('~/.poor-code/auth.json')))['providers']['openai']['api_key'])")"

echo "Starting harness run (gpt-5.4-nano, 10 tasks)"
tb run --agent-import-path bench.poor_code_agent:PoorCodeAgent \
  --dataset terminal-bench-core==0.1.1 --global-agent-timeout-sec 3600 \
  -t grid-pattern-transform -t simple-web-scraper -t openssl-selfsigned-cert \
  -t organization-json-generator -t hello-world -t password-recovery \
  -t fix-git -t csv-to-parquet -t swe-bench-langcodes -t fibonacci-server \
  --n-concurrent 4 --no-livestream
echo "TB_EXIT=$?"
