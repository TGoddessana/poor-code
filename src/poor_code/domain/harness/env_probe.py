"""env_probe — deterministic, read-only snapshot of the execution environment.

The explorer runs this once so downstream nodes (planner, implementer) choose a
tech stack that actually exists in the container. A bench task on bare
ubuntu-24-04 has python3 but no node; without this the implementer happily wrote
a Node server and died on `node: not found`.

Design: there is no universal "describe my environment" tool, so we combine
(1) a broad CURATED probe of common runtimes/compilers/package-managers/VCS —
read with `command -v` + `--version` for human-readable detail, and (2) a full
PATH command INVENTORY as a catch-all, so long-tail tools (conda, pnpm, deno,
rustc, …) we did not curate still show up. Deterministic (not a model-invoked
tool) so it can never be "forgotten"."""
from __future__ import annotations

import asyncio

_MAX_OUTPUT = 7000

# Broad but curated. The PATH inventory below is the catch-all for anything missing.
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
echo "PATH COMMANDS (names only, catch-all):"
for d in $(printf '%s' "$PATH" | tr ':' ' '); do ls -1 "$d" 2>/dev/null; done | sort -u | tr '\n' ' '
echo ""
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
