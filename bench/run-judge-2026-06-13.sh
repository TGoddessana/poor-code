#!/usr/bin/env bash
# 10-task terminal-bench run, gpt-5.4-nano, against the feat/completion-judge branch
# (completion_gate promoted to an LLM judge over the objective floor).
# install.sh installs git+...@${POOR_CODE_GIT_REF} inside the container.
set -uo pipefail

export DOCKER_HOST="unix:///Users/goddessana/.docker/run/docker.sock"
export PYTHONPATH="."
export POOR_CODE_PROVIDER="openai"
export POOR_CODE_MODEL="gpt-5.4-nano"
export POOR_CODE_GIT_REF="feat/completion-judge"   # <-- bench THIS branch, not main
export OPENAI_API_KEY="$(python3 -c "import json,os;print(json.load(open(os.path.expanduser('~/.poor-code/auth.json')))['providers']['openai']['api_key'])")"

echo "Starting harness run (gpt-5.4-nano, 10 tasks, ref=${POOR_CODE_GIT_REF})"
tb run --agent-import-path bench.poor_code_agent:PoorCodeAgent \
  --dataset terminal-bench-core==0.1.1 --global-agent-timeout-sec 3600 \
  -t grid-pattern-transform -t simple-web-scraper -t openssl-selfsigned-cert \
  -t organization-json-generator -t hello-world -t password-recovery \
  -t fix-git -t csv-to-parquet -t swe-bench-langcodes -t fibonacci-server \
  --n-concurrent 4 --no-livestream
echo "TB_EXIT=$?"
