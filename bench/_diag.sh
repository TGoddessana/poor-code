#!/usr/bin/env bash
# Context-fidelity diagnostic: run poor-code headless with gemma over a COPY of the
# real source tree, dumping every node's constructed prompt. Isolated from the repo
# working tree (operates on a temp copy).
set -uo pipefail
REPO="/Users/goddessana/Developments/poor-code"
TMPD="$(mktemp -d)/proj"
mkdir -p "$TMPD"
cp -r "$REPO/src" "$TMPD/src"
DUMP="$REPO/bench/gemma-prompt-dump.txt"
: > "$DUMP"   # truncate
echo "TMPD=$TMPD"
echo "DUMP=$DUMP"

cd "$TMPD"
export POOR_CODE_DUMP_PROMPTS="$DUMP"
export POOR_CODE_PROVIDER="ollama_cloud"
export POOR_CODE_MODEL="gemma4:31b-cloud"
export OLLAMA_API_KEY="$(python3 -c "import json,os;print(json.load(open(os.path.expanduser('~/.poor-code/auth.json')))['providers']['ollama_cloud']['api_key'])")"

uv run --project "$REPO" python -m poor_code --headless \
  "Add input validation to run_shell in src/poor_code/domain/harness/nodes/execution.py: raise ValueError when the command string is empty or whitespace-only." \
  > "$REPO/bench/gemma-diag-report.json" 2> "$REPO/bench/gemma-diag-trace.log"
echo "HEADLESS_EXIT=$?"
