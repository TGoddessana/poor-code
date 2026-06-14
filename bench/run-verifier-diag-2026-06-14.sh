#!/usr/bin/env bash
# Verifier-context diagnostic: gemma4:31b-cloud over the false_accept tasks, with the
# verdict trace dumped to /logs/poorcode-dump.txt (collected into sessions/). Lets each
# false_accept be classified A/B/C/D (weak criteria / unobserved / rubber-stamped /
# fabricated) from artifacts instead of guessed. Tasks come from $@ (default: 1 smoke task).
set -uo pipefail

export DOCKER_HOST="unix:///Users/goddessana/.docker/run/docker.sock"
export PYTHONPATH="."
export POOR_CODE_PROVIDER="ollama_cloud"
export POOR_CODE_MODEL="gemma4:31b-cloud"
export POOR_CODE_GIT_REF="feat/verification-agent"
export POOR_CODE_ADVISORY_GATES="1"
export POOR_CODE_DUMP_PROMPTS="/logs/poorcode-dump.txt"   # container path → sessions/
export OLLAMA_API_KEY="$(python3 -c "import json,os;print(json.load(open(os.path.expanduser('~/.poor-code/auth.json')))['providers']['ollama_cloud']['api_key'])")"

TASKS=("$@")
if [ ${#TASKS[@]} -eq 0 ]; then TASKS=(csv-to-parquet); fi
TARGS=(); for t in "${TASKS[@]}"; do TARGS+=(-t "$t"); done

echo "Verifier-diag run (gemma4:31b-cloud, ref=${POOR_CODE_GIT_REF}, dump on): ${TASKS[*]}"
tb run --agent-import-path bench.poor_code_agent:PoorCodeAgent \
  --dataset terminal-bench-core==0.1.1 --global-agent-timeout-sec 3600 \
  "${TARGS[@]}" --n-concurrent 4 --no-livestream
echo "TB_EXIT=$?"
