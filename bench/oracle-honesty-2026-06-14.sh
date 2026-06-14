#!/usr/bin/env bash
# Oracle-honesty measurement: the 4 known false_accept tasks x N repeats.
# Primary signal = false_accept count (verifier raw=advance AND real tests.log FAIL),
# NOT pass rate (gemma run-to-run variance makes pass rate unusable as a lever signal).
#
# IMPORTANT: POOR_CODE_GIT_REF below selects the branch the in-container agent installs.
# It defaults to the current branch so the run exercises THESE oracle changes — that branch
# must be PUSHED to the remote first (install.sh fetches it inside the container).
set -uo pipefail

export DOCKER_HOST="unix:///Users/goddessana/.docker/run/docker.sock"
export PYTHONPATH="."
export POOR_CODE_PROVIDER="ollama_cloud"
export POOR_CODE_MODEL="gemma4:31b-cloud"
export POOR_CODE_GIT_REF="${POOR_CODE_GIT_REF:-$(git rev-parse --abbrev-ref HEAD)}"
export POOR_CODE_ADVISORY_GATES="1"
export POOR_CODE_DUMP_PROMPTS="/logs/poorcode-dump.txt"   # persist verifier:verdict + oracle authoring trace
export OLLAMA_API_KEY="$(python3 -c "import json,os;print(json.load(open(os.path.expanduser('~/.poor-code/auth.json')))['providers']['ollama_cloud']['api_key'])")"

N="${N:-5}"
OUT="bench/oracle-honesty-$(git rev-parse --short HEAD).log"
echo "Oracle-honesty: 4 false_accept tasks x ${N} (model=${POOR_CODE_MODEL}, ref=${POOR_CODE_GIT_REF})" | tee "$OUT"

for i in $(seq 1 "$N"); do
  echo "=== repeat $i/$N ===" | tee -a "$OUT"
  tb run --agent-import-path bench.poor_code_agent:PoorCodeAgent \
    --dataset terminal-bench-core==0.1.1 --global-agent-timeout-sec 3600 \
    -t heterogeneous-dates -t sqlite-db-truncate \
    -t organization-json-generator -t fibonacci-server \
    --n-concurrent 4 --no-livestream 2>&1 | tee -a "$OUT"
  echo "TB_EXIT=$? (repeat $i)" | tee -a "$OUT"
done

# --- tally (manual, after the loop) ---
# Each task run dir is under runs/<timestamp>/<task>/<task>.1-of-1.*/sessions/. For each:
#   raw_verdict := awk '/NODE: verifier:verdict/{f=1} f' .../sessions/poorcode-dump.txt \
#                  | grep -o '"raw_verdict": "[a-z_]*"' | head -1
#   real        := tail -n 40 .../sessions/tests.log     # graded test PASS/FAIL
#   false_accept  <=>  raw_verdict == advance  AND  real == FAIL
#   abstained     <=>  the spec dump shows a check with status "unknown"
# Report per task across N runs: false_accept, honest_repair, abstained, false_abandon (expect 0).
echo "Tally: compare '\"raw_verdict\": \"advance\"' in poorcode-dump.txt against tests.log PASS/FAIL per task." | tee -a "$OUT"
echo "Wrote $OUT"
