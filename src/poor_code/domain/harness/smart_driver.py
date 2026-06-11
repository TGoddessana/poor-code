"""Smart Driver advisor for HITL steering.

The advisor is deliberately advisory: it reads state and files, emits a structured
decision, and the deterministic Driver validates and applies that decision.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel

from poor_code.domain.harness.node import strip_code_fence, validate_output
from poor_code.domain.llm_schema import inline_refs
from poor_code.domain.session.models import (
    Attempt,
    Cursor,
    NodeFeedbackPacket,
    SessionState,
    Task,
)
from poor_code.provider.events import (
    FinishedReason,
    LLMEvent,
    TextDelta,
    ToolCallEnded,
    ToolCallInputDelta,
    ToolCallStarted,
)
from poor_code.provider.usage import tag


_TRUTHY = {"1", "true", "yes", "on"}
_MAX_FILES = 5
_MAX_BYTES = 20_000
_MAX_LINES = 200
_PATH_RE = re.compile(r"(?P<path>(?:\.{1,2}/)?[\w./@+-]+\.[A-Za-z0-9_+-]+)")
_TOOL_NAME = "decide_driver_action"

_ACTIONS = (
    "answer_only",
    "answer_and_continue",
    "continue_default",
    "restart_current",
    "redirect",
    "redirect_and_inject",
    "bubble_repair",
    "rollback_request",
    "pivot_request",
    "ask_user",
)

_SYSTEM = (
    "You are Smart Driver, a supervisor for a coding harness. A user interrupted "
    "the current run and sent a HITL utterance. Classify the utterance and decide "
    "how the deterministic Driver should proceed. You do not edit files, run "
    "commands, or declare validation passed. You may answer status questions, ask "
    "the user for clarification, restart the current node with targeted feedback, "
    "redirect within the current graph scope, or bubble a repair to an outer graph. "
    "Use the provided plan, task, diff, validation, history, and file excerpts as "
    "evidence. Prefer the smallest useful control action. Call decide_driver_action "
    "exactly once."
)


class _PacketOut(BaseModel):
    target_nodes: list[str] = []
    summary: str = ""
    evidence: list[str] = []
    instruction: str = ""
    ttl_steps: int = 1


class _DecisionOut(BaseModel):
    action: Literal[
        "answer_only",
        "answer_and_continue",
        "continue_default",
        "restart_current",
        "redirect",
        "redirect_and_inject",
        "bubble_repair",
        "rollback_request",
        "pivot_request",
        "ask_user",
    ]
    target_node: str | None = None
    layer: Literal["implementation", "plan", "understanding", "acceptance"] | None = None
    reason: str = ""
    user_message: str = ""
    ask_prompt: str = ""
    feedback_packets: list[_PacketOut] = []


@dataclass(frozen=True)
class AdvisorDecision:
    action: str
    target_node: str | None = None
    layer: str | None = None
    reason: str = ""
    user_message: str = ""
    ask_prompt: str = ""
    feedback_packets: tuple[NodeFeedbackPacket, ...] = ()


@dataclass(frozen=True)
class AdviceRequest:
    state: SessionState
    graph_name: str
    current_node: str
    available_nodes: tuple[str, ...]
    cwd: Path


class DriverAdvisor(Protocol):
    async def advise(self, req: AdviceRequest) -> AdvisorDecision: ...


def smart_driver_enabled(env: dict[str, str] | None = None) -> bool:
    source = os.environ if env is None else env
    return source.get("POORCODE_SMART_DRIVER", "").strip().lower() in _TRUTHY


def build_smart_driver_advisor(base_llm: Any, cwd: Path) -> DriverAdvisor | None:
    if not smart_driver_enabled():
        return None
    llm = _override_llm(base_llm)
    return SmartDriverAdvisor(llm=llm, cwd=cwd)


def _override_llm(base_llm: Any) -> Any:
    provider = os.environ.get("POORCODE_SMART_DRIVER_PROVIDER", "").strip()
    model = os.environ.get("POORCODE_SMART_DRIVER_MODEL", "").strip()
    api_key = os.environ.get("POORCODE_SMART_DRIVER_API_KEY", "").strip()
    if provider and model and api_key:
        from poor_code.provider.providers import build_llm
        return build_llm(provider, model=model, api_key=api_key)
    return base_llm


class SmartDriverAdvisor:
    def __init__(self, llm: Any, cwd: Path) -> None:
        self._llm = llm
        self._cwd = Path(cwd)

    async def advise(self, req: AdviceRequest) -> AdvisorDecision:
        raw = strip_code_fence(await self._stream_once(req))
        out = validate_output(_DecisionOut, raw, node="smart_driver")
        source_index = len(req.state.steering_notes)
        packets = tuple(
            NodeFeedbackPacket(
                target_nodes=tuple(p.target_nodes),
                summary=p.summary,
                evidence=tuple(p.evidence),
                instruction=p.instruction,
                ttl_steps=max(1, p.ttl_steps),
                source_steering_index=source_index,
            )
            for p in out.feedback_packets
            if p.target_nodes and (p.summary or p.instruction)
        )
        return AdvisorDecision(
            action=out.action,
            target_node=out.target_node,
            layer=out.layer,
            reason=out.reason,
            user_message=out.user_message,
            ask_prompt=out.ask_prompt,
            feedback_packets=packets,
        )

    async def _stream_once(self, req: AdviceRequest) -> str:
        tag(self._llm, "smart_driver")
        messages = [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": self._briefing(req)},
        ]
        tools = [_decision_tool()]
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": _TOOL_NAME,
                "schema": tools[0]["function"]["parameters"],
            },
        }
        args_by_call: dict[str, str] = {}
        order: list[str] = []
        content: list[str] = []
        async for ev in self._llm.stream(
            messages=messages, tools=tools, response_format=response_format
        ):
            if isinstance(ev, TextDelta):
                content.append(ev.text)
            elif isinstance(ev, ToolCallStarted):
                args_by_call[ev.call_id] = ""
                order.append(ev.call_id)
            elif isinstance(ev, ToolCallInputDelta):
                if ev.call_id in args_by_call:
                    args_by_call[ev.call_id] += ev.json_delta
            elif isinstance(ev, (ToolCallEnded, FinishedReason, LLMEvent)):
                pass
        if order:
            return args_by_call[order[0]] or "{}"
        return "".join(content)

    def _briefing(self, req: AdviceRequest) -> str:
        state = req.state
        utterance = state.steering_notes[-1] if state.steering_notes else ""
        parts = [
            f"HITL UTTERANCE:\n{utterance}",
            f"GRAPH SCOPE: {req.graph_name}",
            f"CURRENT NODE: {req.current_node}",
            f"AVAILABLE NODES: {', '.join(req.available_nodes) or '(none)'}",
            f"OUTER CURSOR:\n{_cursor_digest(state.cursor)}",
            f"CHILD CURSORS:\n{_child_cursor_digest(state)}",
            f"PENDING QUERY:\n{_pending_query_digest(state)}",
            f"REQUEST:\n{getattr(state.request, 'raw_text', '') if state.request else '(none)'}",
            f"REQUIREMENT:\n{getattr(state.requirement, 'summary', '') if state.requirement else '(none)'}",
            f"ACCEPTANCE:\n{_acceptance_digest(state)}",
            f"PLAN:\n{_plan_digest(state)}",
            f"ACTIVE TASK:\n{_task_digest(_active_task(state))}",
            f"LATEST ATTEMPT:\n{_attempt_digest(_latest_attempt(state))}",
            f"RECENT HISTORY:\n{_history_digest(state)}",
            f"FILE EXCERPTS:\n{self._file_excerpts(state, utterance)}",
            "ACTION GUIDANCE:\n"
            "- For pure status questions, use answer_only and ask whether to continue.\n"
            "- If the user says to explain and continue, use answer_and_continue.\n"
            "- If implementation feedback targets the current work, use restart_current "
            "with a packet for implementer/validator/composer as appropriate.\n"
            "- If there is a pending interview/query and the user objects to it, "
            "use restart_current with feedback for interviewer to ask a better "
            "question, answer_and_continue if the utterance resolves the issue, "
            "or redirect/bubble_repair if the problem is bad exploration/planning.\n"
            "- If the plan/decomposition is wrong inside an implementation subgraph, "
            "use bubble_repair with layer='plan'.\n"
            "- For rollback requests, use rollback_request or ask_user; never claim rollback happened.\n"
            "- For pivots, choose pivot_request with a target node such as router or planner.",
        ]
        return "\n\n".join(parts)

    def _file_excerpts(self, state: SessionState, utterance: str) -> str:
        rels = _candidate_files(state, utterance)
        blocks: list[str] = []
        for rel in rels[:_MAX_FILES]:
            block = _read_excerpt(self._cwd, rel)
            if block:
                blocks.append(block)
        return "\n\n".join(blocks) if blocks else "(none)"


def _decision_tool() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": _TOOL_NAME,
            "description": "Decide how the Driver should handle the user's HITL utterance.",
            "parameters": inline_refs(_DecisionOut.model_json_schema()),
        },
    }


def _cursor_digest(cursor: Cursor | None) -> str:
    if cursor is None:
        return "(none)"
    parts = [f"phase={cursor.phase.value}", f"node={cursor.current_node}"]
    if cursor.task_id:
        parts.append(f"task={cursor.task_id}")
    if cursor.attempt_id:
        parts.append(f"attempt={cursor.attempt_id}")
    return ", ".join(parts)


def _child_cursor_digest(state: SessionState) -> str:
    items = state.driver_control.subgraph_cursors
    if not items:
        return "(none)"
    return "\n".join(f"- {item.graph_name}: {_cursor_digest(item.cursor)}" for item in items)


def _acceptance_digest(state: SessionState) -> str:
    if state.acceptance is None or not state.acceptance.checks:
        return "(none)"
    return "\n".join(
        f"- {c.criterion}: {c.command} ({c.rationale})" for c in state.acceptance.checks
    )


def _pending_query_digest(state: SessionState) -> str:
    q = state.pending_query
    if q is None:
        return "(none)"
    parts = [
        f"id={q.id}",
        f"kind={q.kind.value}",
        f"prompt={q.prompt}",
    ]
    if q.context:
        parts.append(f"context={q.context}")
    if q.options:
        parts.append("options=" + ", ".join(q.options))
    if q.resolves:
        parts.append(f"resolves={q.resolves}")
    if q.rationale:
        parts.append(f"rationale={q.rationale}")
    return "\n".join(parts)


def _plan_digest(state: SessionState) -> str:
    plan = state.plan
    if plan is None:
        return "(none)"
    tasks = "\n".join(
        f"- {t.id} [{t.status.value}] editable={','.join(t.edit_scope.editable) or '(none)'}: {t.title}"
        for t in plan.tasks
    )
    md = plan.plan_md[:4000] if plan.plan_md else "(no plan_md)"
    return f"plan_md:\n{md}\n\ntasks:\n{tasks or '(none)'}"


def _active_task(state: SessionState) -> Task | None:
    if state.plan is None or state.cursor is None or state.cursor.task_id is None:
        return None
    return next((t for t in state.plan.tasks if t.id == state.cursor.task_id), None)


def _latest_attempt(state: SessionState) -> Attempt | None:
    task = _active_task(state)
    if task is None or not task.attempts:
        return None
    if state.cursor is not None and state.cursor.attempt_id:
        for attempt in task.attempts:
            if attempt.id == state.cursor.attempt_id:
                return attempt
    return task.attempts[-1]


def _task_digest(task: Task | None) -> str:
    if task is None:
        return "(none)"
    return (
        f"id={task.id}\n"
        f"title={task.title}\n"
        f"purpose={task.purpose}\n"
        f"description={task.description}\n"
        f"editable={', '.join(task.edit_scope.editable) or '(none)'}\n"
        f"readonly={', '.join(task.edit_scope.readonly) or '(none)'}\n"
        f"forbidden={', '.join(task.edit_scope.forbidden) or '(none)'}\n"
        f"validation={task.how_to_validate or '(none)'}"
    )


def _attempt_digest(attempt: Attempt | None) -> str:
    if attempt is None:
        return "(none)"
    patch = attempt.patch
    run = attempt.run_result
    return (
        f"id={attempt.id}\n"
        f"status={attempt.status.value}\n"
        f"files={', '.join(patch.files) if patch else '(none)'}\n"
        f"diff={_clip(patch.diff if patch else '', 5000)}\n"
        f"validation={run.command if run else '(none)'} exit={run.exit_code if run else ''}\n"
        f"validation_output={_clip(run.output if run else '', 3000)}"
    )


def _history_digest(state: SessionState) -> str:
    if not state.history:
        return "(none)"
    return "\n".join(
        f"- {t.from_node} -> {t.to_node} ({t.trigger.value}): {t.reason}"
        for t in state.history[-12:]
    )


def _candidate_files(state: SessionState, utterance: str) -> tuple[str, ...]:
    out: list[str] = []

    def add(path: str | None) -> None:
        if path and path not in out:
            out.append(path)

    for m in _PATH_RE.finditer(utterance):
        add(m.group("path"))
    task = _active_task(state)
    if task is not None:
        for path in (*task.edit_scope.editable, *task.edit_scope.readonly):
            add(path)
        if task.context is not None:
            for ref in task.context.refs:
                add(ref.file)
    attempt = _latest_attempt(state)
    if attempt is not None and attempt.patch is not None:
        for path in attempt.patch.files:
            add(path)
    if state.understanding is not None:
        for ref in (*state.understanding.candidates, *state.understanding.related_tests):
            add(ref.file)
    return tuple(out)


def _read_excerpt(cwd: Path, rel: str) -> str:
    root = cwd.resolve()
    path = (root / rel).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return ""
    if not path.is_file():
        return ""
    data = path.read_bytes()[:_MAX_BYTES]
    text = data.decode("utf-8", errors="replace")
    lines = text.splitlines()
    truncated = len(lines) > _MAX_LINES or path.stat().st_size > _MAX_BYTES
    text = "\n".join(lines[:_MAX_LINES])
    suffix = "\n[truncated]" if truncated else ""
    return f"### {path.relative_to(root)}\n{text}{suffix}"


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n[truncated]"
