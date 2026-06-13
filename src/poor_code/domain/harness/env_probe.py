"""env_probe — deterministic, read-only snapshot of the execution environment.

The explorer runs this once so downstream nodes (planner, implementer) choose a
tech stack that actually exists in the container. A bench task on bare
ubuntu-24-04 has python3 but no node; without this the implementer happily wrote
a Node server and died on `node: not found`.

Design: there is no universal "describe my environment" tool, so we run a broad
CURATED probe of common runtimes/compilers/package-managers/VCS — `command -v` +
`--version` for human-readable detail — and explicitly name the curated tools that
are ABSENT. Deterministic (not a model-invoked tool) so it can never be "forgotten".

We deliberately do NOT dump the full PATH command inventory. It added ~5.5k chars of
irrelevant binary names to every planning/implementer prompt (measured at 37–50% of
the prompt), drowning the actual task signal for weak models — context POLLUTION, not
fidelity. The implementer has a bash tool and discovers any long-tail tool it actually
needs on demand (`command -v <tool>`), which is cheaper and on-target."""
from __future__ import annotations

import asyncio

_MAX_OUTPUT = 7000

# Broad but curated. Long-tail tools not listed are discovered on demand by the
# implementer's bash tool (`command -v <tool>`) — see module docstring.
_TOOLS = (
    "python3 python node deno bun ruby perl php go java dotnet "
    "gcc g++ cc clang rustc "
    "pip pip3 uv pipx poetry npm pnpm yarn cargo mvn gradle make cmake ninja "
    "apt apt-get dnf yum apk pacman brew "
    "git docker podman curl wget jq sqlite3"
)

_SCRIPT = r"""
set +e
echo "OS: $( (. /etc/os-release 2>/dev/null && printf '%s' "$PRETTY_NAME") || uname -sr )"
echo "ARCH: $(uname -m 2>/dev/null)"
echo "TOOLCHAIN (present only):"
for t in %TOOLS%; do
  p=$(command -v "$t" 2>/dev/null) || continue
  v=$("$t" --version 2>&1 | head -1 | cut -c1-80)
  echo "  $t: ${v:-present}"
done
echo "NOT FOUND (curated tools absent here — do NOT use; code requiring them will fail):"
miss=""
for t in %TOOLS%; do
  command -v "$t" >/dev/null 2>&1 || miss="$miss $t"
done
echo " ${miss# }"
""".replace("%TOOLS%", _TOOLS)


async def probe_environment(cwd, timeout: float = 20.0) -> str:
    """Return a bounded text snapshot of OS + available toolchain + PATH commands.
    Never raises — on any failure it returns a short marker so callers can inline
    it unconditionally."""
    try:
        proc = await asyncio.create_subprocess_shell(
            _SCRIPT,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(cwd),
        )
    except (OSError, ValueError) as e:
        return f"ENVIRONMENT PROBE: unavailable ({type(e).__name__}: {e})"
    try:
        out_bytes, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
            await proc.wait()
        except ProcessLookupError:
            pass
        return "ENVIRONMENT PROBE: unavailable (timed out)"

    out = out_bytes.decode("utf-8", errors="replace").strip()
    if not out:
        return "ENVIRONMENT PROBE: unavailable (no output)"
    if len(out) > _MAX_OUTPUT:
        out = out[:_MAX_OUTPUT] + "\n… [environment snapshot truncated]"
    return out
