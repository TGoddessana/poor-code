"""api_probe — turn the libraries an exploration actually imports into GROUND
TRUTH about their real API, by importing them and listing public attributes.

Why this exists: the acceptance_oracle used to design checks from a PROSE summary
alone, so it had to RECALL a library's API from training (it wrote `TextArea.value`
when the real attribute is `TextArea.text` — an AttributeError that made the check
impossible to pass). A weak model's recall is unreliable; an obscure/internal API
defeats even a strong one. Probing `dir(symbol)` for real removes the guess: the
node sees `text` is present and `value` is not, and writes the check correctly.

Deterministic and best-effort: a symbol that can't be imported just yields an
'<unavailable>' line — never an exception. The probe runs the SAME `python` the
acceptance checks will run (via run_shell in the project cwd), so it reflects the
provisioned environment, not this process."""
from __future__ import annotations

import ast
import asyncio
import shlex
import sys
from pathlib import Path

from poor_code.domain.harness.nodes.execution import run_shell
from poor_code.domain.session.models import FileExcerpt

_MAX_SYMBOLS = 12          # bound the probe: enough to cover a feature's libraries
_MAX_ATTRS = 60            # attributes listed per symbol
_PROBE_TIMEOUT = 20        # a single import+dir() is fast; fail closed if it hangs


def _imports_from(source: str) -> list[tuple[str, str]]:
    """(module, imported_name) pairs from `import`/`from x import y`. Relative
    imports (level>0) are skipped — they are local, not third-party libraries."""
    pairs: list[tuple[str, str]] = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return pairs
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                for alias in node.names:
                    if alias.name != "*":
                        pairs.append((node.module, alias.name))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                pairs.append((alias.name, alias.name.split(".")[-1]))
    return pairs


def _is_third_party(module: str) -> bool:
    """A module worth probing: not stdlib, not this project, not relative."""
    if not module or module.startswith("."):
        return False
    top = module.split(".")[0]
    return top not in sys.stdlib_module_names and top != "poor_code"


def _probe_command(module: str, name: str) -> str:
    code = (
        "import importlib\n"
        f"m = importlib.import_module({module!r})\n"
        f"o = getattr(m, {name!r})\n"
        f"print(', '.join(sorted(a for a in dir(o) if not a.startswith('_'))[:{_MAX_ATTRS}]))"
    )
    return "python -c " + shlex.quote(code)


def _select_symbols(
    excerpts: tuple[FileExcerpt, ...], focus_terms: frozenset[str]
) -> list[tuple[str, str]]:
    """Third-party (module, name) pairs imported by the explored code, prioritised:
    a name the requirement/acceptance mentions, or a Class-like (Capitalised) name —
    the things acceptance checks assert against. Deduped, order-preserving, bounded."""
    seen: set[tuple[str, str]] = set()
    ranked: list[tuple[int, tuple[str, str]]] = []
    for ex in excerpts:
        for module, name in _imports_from(ex.text):
            if not _is_third_party(module) or (module, name) in seen:
                continue
            seen.add((module, name))
            in_focus = name in focus_terms
            classlike = name[:1].isupper()
            if not (in_focus or classlike):
                continue
            ranked.append((0 if in_focus else 1, (module, name)))
    ranked.sort(key=lambda r: r[0])
    return [pair for _, pair in ranked[:_MAX_SYMBOLS]]


async def probe_apis(
    excerpts: tuple[FileExcerpt, ...],
    focus_terms: frozenset[str],
    cwd: Path,
    cancel: asyncio.Event,
) -> str:
    """Return a digest of real public APIs for the third-party symbols the explored
    code imports (those the acceptance checks are likely to touch). Empty string when
    there is nothing groundable. Never raises for a single bad import."""
    symbols = _select_symbols(excerpts, focus_terms)
    if not symbols:
        return ""
    lines: list[str] = []
    for module, name in symbols:
        if cancel.is_set():
            break
        code, out = await run_shell(
            _probe_command(module, name), cwd, cancel, timeout=_PROBE_TIMEOUT)
        attrs = out.strip().splitlines()[-1] if out.strip() else ""
        if code == 0 and attrs:
            lines.append(f"{module}.{name} public attrs: {attrs}")
        else:
            lines.append(f"{module}.{name}: <unavailable>")
    return "\n".join(lines)


def focus_terms(*texts: str) -> frozenset[str]:
    """Identifier-like tokens from requirement/acceptance text, used to prioritise
    which imported symbols to probe (e.g. 'TextArea' mentioned in the requirement)."""
    terms: set[str] = set()
    for text in texts:
        token = ""
        for ch in text:
            if ch.isalnum() or ch == "_":
                token += ch
            else:
                if len(token) > 1:
                    terms.add(token)
                token = ""
        if len(token) > 1:
            terms.add(token)
    return frozenset(terms)
