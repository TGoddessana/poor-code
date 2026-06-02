# src/poor_code/domain/harness/headless.py
"""Headless endpoint — runs the harness graph unattended under FULL_AUTO policy.
No Textual. Progress trace → stderr; final Report JSON → stdout. Reuses the same
build_default_registry + Driver as the TUI; policy divergence lives only in the
run-loop (run_headless), Driver is unchanged."""
from __future__ import annotations

import asyncio
import os
import sys
from typing import Any, TextIO

from poor_code.infra import auth_store
from poor_code.provider.providers import ollama_cloud
from poor_code.domain.harness.nodes.reporter import build_report
from poor_code.domain.session.models import ReportOutcome, SessionState, UserResponse


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


def resolve_llm():
    """Env first (container has no auth.json), then on-disk auth_store. None = no creds."""
    key = os.environ.get("OLLAMA_API_KEY")
    model = os.environ.get("POOR_CODE_MODEL")
    if key and model:
        return ollama_cloud.configure(model=model, api_key=key)
    creds = auth_store.get("ollama_cloud")
    if creds and creds.get("api_key") and creds.get("model"):
        return ollama_cloud.configure(model=creds["model"], api_key=creds["api_key"])
    return None


_CANNED_ANSWER = "Proceed using your best judgment. Do not ask further questions."


async def run_headless(driver, state: SessionState, cancel: "asyncio.Event",
                       sink: object | None = None) -> SessionState:
    """FULL_AUTO walk: auto-answer queries; stamp ABANDONED on any non-success park."""
    while True:
        state = await driver.run(state, cancel, sink=sink)
        if state.pending_query is not None:
            state = state.with_user_response(
                UserResponse(query_id=state.pending_query.id, answer=_CANNED_ANSWER))
            continue
        break
    if state.report is None:
        state = state.with_report(build_report(state, ReportOutcome.ABANDONED))
    return state
