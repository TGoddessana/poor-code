# terminal-bench adapter for poor-code

Runs poor-code headless inside a terminal-bench task container.

## One-time host setup
    uv tool install terminal-bench    # provides the `tb` CLI (needs Docker running)
    export OLLAMA_API_KEY=...          # both required
    export POOR_CODE_MODEL=...

## Manual smoke (one task, score ignored)
    tb run --agent-import-path bench.poor_code_agent:PoorCodeAgent --task-id hello-world

terminal-bench v2 / harbor equivalent:
    harbor run -d terminal-bench@2.1 --agent-import-path bench.poor_code_agent:PoorCodeAgent

## What "success" means here
The smoke passes if poor-code installs, runs the graph end-to-end, and exits 0 —
crash-free. The benchmark's own hidden `run-tests.sh` scores file state; our
internal `validation_runner` (`how_to_validate`) is independent of it. Collecting
real scores across the task set is a separate step.
