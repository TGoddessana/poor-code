import asyncio
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
import pytest

from poor_code.domain.harness import build_default_registry, Driver, route
from poor_code.domain.session.models import (
    SessionState, Cursor, Phase, Request, RequestKind, ReportOutcome, TaskStatus)
from poor_code.domain.session.store import SessionStore
from poor_code.domain.project_map.models import ProjectMap
from poor_code.provider.events import (
    TextDelta, ToolCallStarted, ToolCallInputDelta, ToolCallEnded, FinishedReason)


class E2ELLM:
    """One scripted client for the whole graph, keyed by the offered tool name.
    Implementer rounds (tools start with 'write') write out.txt once then stop."""
    def __init__(self):
        self._impl_round = 0

    async def stream(self, messages, tools):
        name = tools[0]["function"]["name"]
        canned = {
            "classify_request": {"kind": "engineering", "reason": "t"},
            "emit_code_context": {"candidates": [{"file": "out.txt"}],
                                  "confusers": [], "related_tests": []},
            "interview_step": {"action": "done",
                               "requirement": {"summary": "create out.txt",
                                               "acceptance": ["out.txt exists"]}},
            "emit_plan": {"tasks": [{"title": "make out.txt", "purpose": "p",
                                     "edit_scope": {"editable": ["out.txt"]},
                                     "how_to_validate": "test -f out.txt"}],
                          "deps": []},
            "judge": {"verdict": "advance", "hint": ""},
        }
        if name == "write":  # implementer tool loop
            self._impl_round += 1
            if self._impl_round == 1:
                yield ToolCallStarted(call_id="w1", name="write")
                yield ToolCallInputDelta(call_id="w1",
                                         json_delta='{"path":"out.txt","content":"ok"}')
                yield ToolCallEnded(call_id="w1")
                yield FinishedReason(reason="tool_calls")
            else:
                yield TextDelta(text="done")
                yield FinishedReason(reason="stop")
            return
        if name not in canned:  # explorer stage ① exploration round → stop
            yield TextDelta(text="enough")
            yield FinishedReason(reason="stop")
            return
        yield ToolCallStarted(call_id="c1", name=name)
        yield ToolCallInputDelta(call_id="c1", json_delta=json.dumps(canned[name]))
        yield ToolCallEnded(call_id="c1")
        yield FinishedReason(reason="tool_calls")


def _map(cwd):
    return ProjectMap(version=2, generated_at=datetime.now(UTC), cwd=cwd,
                      files=(), parse_errors=())


@pytest.mark.asyncio
async def test_full_execution_reaches_reporter_and_writes_file(tmp_path):
    reg = build_default_registry(llm=E2ELLM(), project_map=_map(tmp_path))
    store = SessionStore(tmp_path / ".poor-code")
    sid = uuid.uuid4().hex

    def on_step(s):
        store.write_session_state(sid, s)
        store.write_attempt_artifacts(sid, s)

    driver = Driver(reg, route, on_step=on_step)
    start = SessionState(
        cursor=Cursor(phase=Phase.ROUTING, current_node="router"),
        request=Request(raw_text="create out.txt", kind=RequestKind.ENGINEERING))
    final = await driver.run(start, asyncio.Event())

    # the graph ran through reporter (registered) and terminated
    assert final.cursor.current_node == "reporter"
    assert final.cursor.phase is Phase.FINALIZING
    assert final.report is not None
    assert final.report.outcome is ReportOutcome.SUCCEEDED
    # the implementer actually created the file in the work tree
    assert (tmp_path / "out.txt").read_text() == "ok"
    # the task completed via the binding runner
    assert final.plan.tasks[0].status is TaskStatus.DONE
    # per-attempt artifacts landed on disk
    from poor_code.domain.session import paths
    aid = final.plan.tasks[0].attempts[-1].id
    adir = paths.attempt_dir(tmp_path / ".poor-code", sid, "t1", aid)
    assert (adir / "run_result.json").exists()
    assert (adir / "diff.patch").exists()
