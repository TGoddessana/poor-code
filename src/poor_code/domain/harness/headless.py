# src/poor_code/domain/harness/headless.py
"""Headless endpoint — runs the harness graph unattended under FULL_AUTO policy.
No Textual. Progress trace → stderr; final Report JSON → stdout. Reuses the same
build_default_registry + Driver as the TUI; policy divergence lives only in the
run-loop (run_headless), Driver is unchanged."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

from poor_code.infra import auth_store, paths
from poor_code.provider.providers import build_llm
from poor_code.domain.harness.nodes.reporter import build_report, report_to_dict
from poor_code.domain.project_map import ProjectMap, ProjectMapStore
from poor_code.domain.session.models import (
    Cursor, Phase, Policy, Request, RequestKind,
    ReportOutcome, SessionState, UserResponse,
)


class StderrSink:
    """Human-readable progress trace. Same method surface as TurnSink so it is a
    drop-in NodeContext.sink. Writes to `stream` (default sys.stderr)."""

    def __init__(self, stream: TextIO | None = None) -> None:
        self._out = stream if stream is not None else sys.stderr

    def _w(self, line: str) -> None:
        self._out.write(line + "\n")
        self._out.flush()

    # node-facing
    def node_entered(self, node: str, phase: str) -> None:
        self._w(f"▸ {node} [{phase}]")

    def node_repaired(self, node: str, detail: str) -> None:
        # Surface WHY a gate sent work back (e.g. eng_gate's scope violation).
        self._w(f"  ↺ {node} {detail}")

    def text_delta(self, text: str) -> None:
        if text:
            self._out.write(text)
            self._out.flush()

    def tool_started(self, tool_call_id: str, tool_name: str, args: dict[str, Any]) -> None:
        self._w(f"  · {tool_name} {args}")

    def tool_finished(self, tool_call_id: str, result: Any) -> None:
        self._w(f"  ✓ {str(result)[:200]}")

    def tool_failed(self, tool_call_id: str, error: str) -> None:
        self._w(f"  ✗ {error}")

    # app-facing (not invoked by Driver during run; provided for compatibility)
    def query_raised(self, query: Any) -> None:
        self._w(f"❓ {getattr(query, 'prompt', query)}")

    def plan_ready(self, plan: Any) -> None:
        self._w("📋 plan ready")

    def report_ready(self, report: Any) -> None:
        self._w(f"■ {getattr(report, 'summary', report)}")

    def forward(self, event: Any) -> None:
        pass


# Per-provider env var holding that provider's API key. POOR_CODE_API_KEY is a
# provider-agnostic override that wins over these when set.
_PROVIDER_KEY_ENV = {
    "ollama_cloud": "OLLAMA_API_KEY",
    "openai": "OPENAI_API_KEY",
}


def resolve_llm():
    """Env first (container has no auth.json), then on-disk auth_store. None = no creds.

    Provider is chosen by POOR_CODE_PROVIDER (default 'ollama_cloud'); the key is
    read from POOR_CODE_API_KEY or the provider's own env var. Goes through the
    central build_llm registry so headless tracks the same provider set as the UI.
    """
    provider = os.environ.get("POOR_CODE_PROVIDER", "ollama_cloud")
    model = os.environ.get("POOR_CODE_MODEL")
    key = (os.environ.get("POOR_CODE_API_KEY")
           or os.environ.get(_PROVIDER_KEY_ENV.get(provider, ""), "") or "")
    if key and model:
        return build_llm(provider, model=model, api_key=key)
    creds = auth_store.get(provider)
    if creds and creds.get("api_key") and creds.get("model"):
        return build_llm(provider, model=creds["model"], api_key=creds["api_key"])
    return None


_CANNED_ANSWER = "Proceed using your best judgment. Do not ask further questions."
MAX_AUTO_ANSWERS = 20  # safety cap: headless must terminate even if a node asks forever


async def run_headless(driver, state: SessionState, cancel: "asyncio.Event",
                       sink: object | None = None) -> SessionState:
    """FULL_AUTO walk: auto-answer queries (bounded by MAX_AUTO_ANSWERS); stamp
    ABANDONED on any non-success park or if the auto-answer cap is exhausted."""
    auto_answers = 0
    while True:
        state = await driver.run(state, cancel, sink=sink)
        if state.pending_query is not None and auto_answers < MAX_AUTO_ANSWERS:
            auto_answers += 1
            state = state.with_user_response(
                UserResponse(query_id=state.pending_query.id, answer=_CANNED_ANSWER))
            continue
        break
    if state.report is None:
        state = state.with_report(build_report(state, ReportOutcome.ABANDONED))
    return state


def _load_project_map(cwd: Path) -> ProjectMap:
    try:
        return ProjectMapStore().read(paths.config_dir(cwd))
    except (FileNotFoundError, ValueError):
        return ProjectMap(version=2, generated_at=datetime.now(UTC),
                          cwd=cwd, files=(), parse_errors=())


def _build_driver(llm) -> object:
    from poor_code.domain.harness import build_default_graph
    from poor_code.domain.harness.driver import Driver

    cwd = Path.cwd()
    graph = build_default_graph(llm=llm, project_map=_load_project_map(cwd))
    return Driver(graph.nodes, graph.edges.route)


async def main(instruction: str, *, stdout=None, stderr=None) -> int:
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    llm = resolve_llm()
    if llm is None:
        err.write("no credentials: set POOR_CODE_MODEL + a provider key "
                  "(OLLAMA_API_KEY, or POOR_CODE_PROVIDER=openai with OPENAI_API_KEY) "
                  "(or run `poor-code` and /login)\n")
        return 2
    try:
        driver = _build_driver(llm)
        sink = StderrSink(stream=err)
        state = SessionState(
            cursor=Cursor(phase=Phase.ROUTING, current_node="router"),
            request=Request(raw_text=instruction, kind=RequestKind.ENGINEERING),
            policy=Policy.FULL_AUTO)
        final = await run_headless(driver, state, asyncio.Event(), sink=sink)
        payload = report_to_dict(final.report)
        meter = getattr(llm, "meter", None)
        if meter is not None:
            # Real token counts for this run (input/output/cache), total + per-node.
            # The research found results.json token counts were always 0; this is the
            # measurement that lets us see context bloat and whether caching happened.
            payload["token_usage"] = meter.snapshot()
            t = meter.total
            err.write(
                f"tokens: in={t.input_tokens} out={t.output_tokens} "
                f"cached={t.cached_input_tokens} calls={t.calls}\n")
            err.flush()
        out.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        out.flush()
        return 0
    except Exception as exc:  # noqa: BLE001 — top-level headless guard: report cleanly, exit 1
        err.write(f"error: {type(exc).__name__}: {exc}\n")
        return 1
