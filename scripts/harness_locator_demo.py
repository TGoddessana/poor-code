"""Run the harness graph end-to-end against a REAL LLM.

This drives the v1 runtime skeleton (Router -> Locator -> park) with the same
provider the TUI uses. It is the only runnable entry point into `domain/harness/`
until the graph is wired into the app, so it doubles as a manual smoke test.

What it does:
  1. Loads the saved Ollama Cloud credentials (run `poor-code` + `/login` first).
  2. Builds a ProjectMap of the current working directory.
  3. Assembles the default registry (Router + Locator) and walks it with the Driver.
  4. Prints every cursor transition and the final symbol-grounded CodeContext.

Usage:
    python scripts/harness_locator_demo.py
    python scripts/harness_locator_demo.py "fix the login bug in the auth flow"
    python scripts/harness_locator_demo.py --cwd /path/to/repo "your request"

The engineering path parks at `interviewer` (not built yet) after the Locator
produces a CodeContext. A greeting (e.g. "hi") is reclassified by the Router as
lightweight and parks at `fast_path` without ever reaching the Locator.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from poor_code.domain.harness import Driver, build_default_registry, route
from poor_code.domain.project_map import BuildProgress, make_default_builder
from poor_code.domain.session.models import (
    Cursor,
    Phase,
    Request,
    RequestKind,
    SessionState,
)
from poor_code.infra import auth_store
from poor_code.provider.providers import ollama_cloud

_DEFAULT_REQUEST = "find the code that routes between graph nodes in the harness"


def _load_llm():
    """Return a configured LLM client, or exit with a hint if unauthenticated."""
    creds = auth_store.get("ollama_cloud")
    if not creds or not creds.get("api_key") or not creds.get("model"):
        sys.exit(
            "No Ollama Cloud credentials found.\n"
            "Run `poor-code`, type `/login`, and provide your API key + model first."
        )
    print(f"• provider : ollama cloud (model={creds['model']})")
    return ollama_cloud.configure(model=creds["model"], api_key=creds["api_key"])


def _build_map(cwd: Path):
    """Build a ProjectMap of `cwd`, showing scan progress on one line."""
    print(f"• scanning : {cwd}")
    builder = make_default_builder()

    def _progress(p: BuildProgress) -> None:
        print(f"\r  parsing {p.files_processed}/{p.files_total} files…", end="", flush=True)

    pmap = builder.build(cwd, on_progress=_progress)
    n_symbols = sum(len(fe.symbols) for fe in pmap.files)
    print(f"\r• map     : {len(pmap.files)} files, {n_symbols} symbols"
          f"{f', {len(pmap.parse_errors)} parse errors' if pmap.parse_errors else ''}")
    return pmap


def _print_refs(label: str, refs) -> None:
    if not refs:
        print(f"  {label}: (none)")
        return
    print(f"  {label}:")
    for r in refs:
        where = r.file if r.symbol is None else f"{r.file}::{r.symbol}"
        line = f" :{r.lineno}" if r.lineno is not None else ""
        print(f"    - {where}{line}")


async def _run(request_text: str, cwd: Path) -> None:
    print("=" * 70)
    print(f"REQUEST: {request_text!r}")
    print("=" * 70)

    llm = _load_llm()
    pmap = _build_map(cwd)
    registry = build_default_registry(llm=llm, project_map=pmap)

    start = SessionState(
        cursor=Cursor(phase=Phase.ROUTING, current_node="router"),
        request=Request(raw_text=request_text, kind=RequestKind.ENGINEERING),
    )

    print("\n— walking the graph —")
    print(f"  start @ {start.cursor.current_node}")
    driver = Driver(
        registry,
        route,
        on_step=lambda s: print(f"  → {s.cursor.current_node} (phase={s.cursor.phase.value})"),
    )

    try:
        final = await driver.run(start, asyncio.Event())
    except ValueError as e:
        # AgentNode raises this when the model returns no structured tool call.
        sys.exit(f"\nLocator produced no structured output: {e}\n"
                 "(The model may not have called the forced output tool — try a stronger model.)")

    print("\n— result —")
    parked = final.cursor.current_node
    if parked == "fast_path":
        print(f"  Router reclassified this as LIGHTWEIGHT → parked at '{parked}'"
              " (the legacy agent.py path). Locator was never reached.")
        return

    print(f"  parked at '{parked}' (next node not built yet — this is expected)")
    cc = final.understanding
    if cc is None:
        print("  (no CodeContext produced)")
        return
    print("\n  CodeContext (symbol-grounded, from the Locator):")
    _print_refs("candidates   ", cc.candidates)
    _print_refs("confusers    ", cc.confusers)
    _print_refs("related_tests", cc.related_tests)
    print(f"\n  transitions logged: {len(final.history)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Drive the harness graph against a real LLM.")
    parser.add_argument("request", nargs="?", default=_DEFAULT_REQUEST,
                        help="the user request to route + locate (default: a self-referential query)")
    parser.add_argument("--cwd", type=Path, default=Path.cwd(),
                        help="repository to build the ProjectMap from (default: current dir)")
    args = parser.parse_args()
    asyncio.run(_run(args.request, args.cwd.resolve()))


if __name__ == "__main__":
    main()
