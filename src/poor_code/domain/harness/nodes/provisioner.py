"""provisioner [C] — bootstraps the project's test environment in the working tree,
ONCE, after plan approval and before the implementation layer. terminal-bench task
containers ship only source (no pytest, no deps, no built C-extensions); without this
every validation dies 'pytest not found' / 'No module named ...' and the model gets
zero feedback to refine a near-correct fix. This is the terminal-native setup the gold
solver's run-tests.sh performs in an isolated venv — we do it in-place.

Best effort by contract: it NEVER fails the run (always ADVANCE). A failed install
leaves the env no worse than before; a successful one unblocks the validation loop."""
from __future__ import annotations

from pathlib import Path

from poor_code.domain.harness.node import NodeContext, NodeResult
from poor_code.domain.harness.nodes.execution import run_shell
from poor_code.domain.session.models import Verdict, VerdictKind

# Ensure a C compiler exists (slim bases lack one; numpy/astropy C-extensions need it).
_ENSURE_CC = (
    "command -v cc >/dev/null 2>&1 || command -v gcc >/dev/null 2>&1 || "
    "(apt-get update -qq && apt-get install -y -qq --no-install-recommends "
    "gcc g++ python3-dev) || true"
)
# Editable install with extras fallback so the project's own deps + pytest land.
_EDITABLE_INSTALL = (
    "python -m pip install -q -e '.[test]' || "
    "python -m pip install -q -e '.[dev]' || "
    "python -m pip install -q -e . || true"
)
# Guarantee pytest even if the project declares no test extra.
_ENSURE_PYTEST = "python -m pip install -q pytest || true"


def plan_commands(cwd: Path) -> list[str]:
    """Ordered best-effort bootstrap commands for the project rooted at `cwd`. Empty
    when there is no Python project marker (greenfield / non-Python) — the provisioner
    then no-ops, so it is safe in front of every task."""
    if (cwd / "pyproject.toml").exists() or (cwd / "setup.py").exists():
        return [_ENSURE_CC, _EDITABLE_INSTALL, _ENSURE_PYTEST]
    return []


class Provisioner:
    name = "provisioner"

    _TIMEOUT = 600  # editable installs (with a C-extension build) are slow

    def __init__(self, cwd: Path) -> None:
        self._cwd = cwd

    async def run(self, ctx: NodeContext) -> NodeResult:
        for i, cmd in enumerate(plan_commands(self._cwd)):
            cid = f"provision-{i}"
            if ctx.sink is not None:
                ctx.sink.tool_started(cid, "provision", {"cmd": cmd})
            exit_code, output = await run_shell(
                cmd, self._cwd, ctx.cancel, timeout=self._TIMEOUT)
            if ctx.sink is not None:
                ctx.sink.tool_finished(cid, f"[exit {exit_code}] {output[-400:]}")
        return NodeResult(verdict=Verdict(kind=VerdictKind.ADVANCE))
