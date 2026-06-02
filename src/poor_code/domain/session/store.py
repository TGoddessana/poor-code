"""Disk I/O for session/task artifacts. Internal — do not import outside this package."""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from poor_code.domain.session import paths
from poor_code.domain.session.models import (
    AnsweredQuery,
    ChangeSet,
    CodeContext,
    CodeRef,
    Cursor,
    Attempt,
    AttemptStatus,
    ChangeRecord,
    ValidationResult,
    Verdict,
    VerdictKind,
    Layer,
    FeedbackEntry,
    FeedbackMemory,
    Dependency,
    EditScope,
    Phase,
    Plan,
    Policy,
    WorkItemPolicies,
    Query,
    QueryKind,
    Request,
    RequestKind,
    Requirement,
    Session,
    SessionState,
    SessionStatus,
    Task,
    TaskContext,
    TaskStatus,
    WorkItem,
    WorkItemState,
    WorkItemStatus,
    Transition,
    TriggerKind,
    UserResponse,
)


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    """Write JSON atomically: tmp file → os.replace.

    Guarantees that the original file at `path` (if any) is never partially overwritten:
    on any failure before os.replace, the original survives untouched. On failure of
    os.replace itself, the temporary file is cleaned up so it doesn't accumulate.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    try:
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"corrupt session file at {path}: {e}") from e


def _session_to_dict(s: Session) -> dict[str, Any]:
    return {
        "session_id": s.session_id,
        "cwd": str(s.cwd),
        "created_at": s.created_at.isoformat(),
        "parent_session_id": s.parent_session_id,
        "version": s.version,
    }


def _dict_to_session(d: dict[str, Any], src: Path) -> Session:
    try:
        return Session(
            session_id=d["session_id"],
            cwd=Path(d["cwd"]),
            created_at=datetime.fromisoformat(d["created_at"]),
            parent_session_id=d.get("parent_session_id"),
            version=d.get("version", 1),
        )
    except (KeyError, TypeError, ValueError) as e:
        raise ValueError(f"corrupt session file at {src}: {e}") from e


def _ref_to_dict(r: CodeRef) -> dict[str, Any]:
    return {"file": r.file, "symbol": r.symbol, "lineno": r.lineno}


def _dict_to_ref(d: dict[str, Any]) -> CodeRef:
    return CodeRef(file=d["file"], symbol=d.get("symbol"), lineno=d.get("lineno"))


def _query_to_dict(q: Query) -> dict[str, Any]:
    return {"id": q.id, "kind": q.kind.value, "prompt": q.prompt,
            "context": q.context, "options": list(q.options),
            "resolves": q.resolves, "rationale": q.rationale}


def _dict_to_query(d: dict[str, Any]) -> Query:
    return Query(id=d["id"], kind=QueryKind(d["kind"]), prompt=d["prompt"],
                 context=d.get("context"), options=tuple(d.get("options", ())),
                 resolves=d.get("resolves"), rationale=d.get("rationale"))


def _requirement_to_dict(r: Requirement) -> dict[str, Any]:
    return {"summary": r.summary, "acceptance": list(r.acceptance),
            "out_of_scope": list(r.out_of_scope), "assumptions": list(r.assumptions),
            "open_questions": list(r.open_questions)}


def _dict_to_requirement(d: dict[str, Any]) -> Requirement:
    return Requirement(summary=d["summary"], acceptance=tuple(d.get("acceptance", ())),
                       out_of_scope=tuple(d.get("out_of_scope", ())),
                       assumptions=tuple(d.get("assumptions", ())),
                       open_questions=tuple(d.get("open_questions", ())))


def _edit_scope_to_dict(s: EditScope) -> dict[str, Any]:
    return {
        "editable": list(s.editable),
        "readonly": list(s.readonly),
        "forbidden": list(s.forbidden),
    }


def _dict_to_edit_scope(d: dict[str, Any]) -> EditScope:
    return EditScope(
        editable=tuple(d.get("editable", ())),
        readonly=tuple(d.get("readonly", ())),
        forbidden=tuple(d.get("forbidden", ())),
    )


def _task_context_to_dict(c: TaskContext) -> dict[str, Any]:
    return {"refs": [_ref_to_dict(r) for r in c.refs], "snippet": c.snippet}


def _dict_to_task_context(d: dict[str, Any]) -> TaskContext:
    return TaskContext(
        refs=tuple(_dict_to_ref(r) for r in d.get("refs", ())),
        snippet=d.get("snippet"),
    )


def _feedback_entry_to_dict(e: FeedbackEntry) -> dict[str, Any]:
    return {"failure_type": e.failure_type, "symptom": e.symptom,
            "prevention_hint": e.prevention_hint, "task_ref": e.task_ref}


def _dict_to_feedback_entry(d: dict[str, Any]) -> FeedbackEntry:
    return FeedbackEntry(failure_type=d["failure_type"], symptom=d["symptom"],
                         prevention_hint=d["prevention_hint"], task_ref=d.get("task_ref"))


def _verdict_to_dict(v: Verdict) -> dict[str, Any]:
    return {"kind": v.kind.value,
            "layer": None if v.layer is None else v.layer.value,
            "hint": v.hint,
            "query": v.query}


def _dict_to_verdict(d: dict[str, Any]) -> Verdict:
    return Verdict(kind=VerdictKind(d["kind"]),
                   layer=None if d.get("layer") is None else Layer(d["layer"]),
                   hint=d.get("hint"),
                   query=d.get("query"))


def _change_record_to_dict(c: ChangeRecord) -> dict[str, Any]:
    return {"files": list(c.files), "diff": c.diff}


def _dict_to_change_record(d: dict[str, Any]) -> ChangeRecord:
    return ChangeRecord(files=tuple(d.get("files", ())), diff=d.get("diff", ""))


def _changeset_to_dict(c: ChangeSet) -> dict[str, Any]:
    return {"aggregate_diff": c.aggregate_diff,
            "per_task": [[tid, diff] for (tid, diff) in c.per_task]}


def _dict_to_changeset(d: dict[str, Any]) -> ChangeSet:
    return ChangeSet(
        aggregate_diff=d.get("aggregate_diff", ""),
        per_task=tuple((row[0], row[1]) for row in d.get("per_task", ())),
    )


def _validation_result_to_dict(r: ValidationResult) -> dict[str, Any]:
    return {"command": r.command, "exit_code": r.exit_code,
            "passed": r.passed, "output": r.output}


def _dict_to_validation_result(d: dict[str, Any]) -> ValidationResult:
    return ValidationResult(command=d["command"], exit_code=d["exit_code"],
                            passed=d["passed"], output=d.get("output", ""))


def _attempt_to_dict(a: Attempt) -> dict[str, Any]:
    return {
        "id": a.id,
        "patch": None if a.patch is None else _change_record_to_dict(a.patch),
        "assumptions": list(a.assumptions),
        "validator_verdict": None if a.validator_verdict is None else _verdict_to_dict(a.validator_verdict),
        "run_result": None if a.run_result is None else _validation_result_to_dict(a.run_result),
        "gate_verdict": None if a.gate_verdict is None else _verdict_to_dict(a.gate_verdict),
        "adversarial_rounds": a.adversarial_rounds,
        "status": a.status.value,
    }


def _dict_to_attempt(d: dict[str, Any]) -> Attempt:
    return Attempt(
        id=d["id"],
        patch=None if d.get("patch") is None else _dict_to_change_record(d["patch"]),
        assumptions=tuple(d.get("assumptions", ())),
        validator_verdict=None if d.get("validator_verdict") is None else _dict_to_verdict(d["validator_verdict"]),
        run_result=None if d.get("run_result") is None else _dict_to_validation_result(d["run_result"]),
        gate_verdict=None if d.get("gate_verdict") is None else _dict_to_verdict(d["gate_verdict"]),
        adversarial_rounds=d.get("adversarial_rounds", 0),
        status=AttemptStatus(d.get("status", AttemptStatus.ACTIVE.value)),
    )


def _plan_task_to_dict(t: Task) -> dict[str, Any]:
    return {
        "id": t.id,
        "title": t.title,
        "purpose": t.purpose,
        "description": t.description,
        "edit_scope": _edit_scope_to_dict(t.edit_scope),
        "how_to_validate": t.how_to_validate,
        "status": t.status.value,
        "context": None if t.context is None else _task_context_to_dict(t.context),
        "attempts": [_attempt_to_dict(a) for a in t.attempts],
    }


def _dict_to_plan_task(d: dict[str, Any]) -> Task:
    ctx = d.get("context")
    return Task(
        id=d["id"],
        title=d["title"],
        purpose=d["purpose"],
        description=d.get("description", ""),
        edit_scope=_dict_to_edit_scope(d.get("edit_scope", {})),
        how_to_validate=d.get("how_to_validate", ""),
        status=TaskStatus(d.get("status", TaskStatus.PENDING.value)),
        context=None if ctx is None else _dict_to_task_context(ctx),
        attempts=tuple(_dict_to_attempt(a) for a in d.get("attempts", ())),
    )


def _plan_to_dict(p: Plan) -> dict[str, Any]:
    return {
        "tasks": [_plan_task_to_dict(t) for t in p.tasks],
        "deps": [
            {"task_id": d.task_id, "depends_on": d.depends_on}
            for d in p.deps
        ],
    }


def _dict_to_plan(d: dict[str, Any]) -> Plan:
    return Plan(
        tasks=tuple(_dict_to_plan_task(t) for t in d.get("tasks", ())),
        deps=tuple(
            Dependency(task_id=x["task_id"], depends_on=x["depends_on"])
            for x in d.get("deps", ())
        ),
    )


def _answered_to_dict(a: AnsweredQuery) -> dict[str, Any]:
    return {"query": _query_to_dict(a.query),
            "response": {"query_id": a.response.query_id, "answer": a.response.answer,
                         "chosen_option": a.response.chosen_option}}


def _dict_to_answered(d: dict[str, Any]) -> AnsweredQuery:
    r = d["response"]
    return AnsweredQuery(query=_dict_to_query(d["query"]),
                         response=UserResponse(query_id=r["query_id"], answer=r["answer"],
                                               chosen_option=r.get("chosen_option")))


def _session_state_to_dict(st: SessionState) -> dict[str, Any]:
    from poor_code.domain.harness.nodes.reporter import report_to_dict
    cc = st.understanding
    return {
        "status": st.status.value,
        "active_task_id": st.active_task_id,
        "cursor": (
            None if st.cursor is None else {
                "phase": st.cursor.phase.value,
                "current_node": st.cursor.current_node,
                "task_id": st.cursor.task_id,
                "attempt_id": st.cursor.attempt_id,
            }
        ),
        "request": (
            None if st.request is None else
            {"raw_text": st.request.raw_text, "kind": st.request.kind.value}
        ),
        "understanding": (
            None if cc is None else {
                "candidates": [_ref_to_dict(r) for r in cc.candidates],
                "confusers": [_ref_to_dict(r) for r in cc.confusers],
                "related_tests": [_ref_to_dict(r) for r in cc.related_tests],
                "search_notes": cc.search_notes,
            }
        ),
        "history": [
            {"from_node": t.from_node, "to_node": t.to_node,
             "trigger": t.trigger.value, "reason": t.reason, "ts_iso": t.ts_iso}
            for t in st.history
        ],
        "requirement": (None if st.requirement is None
                        else _requirement_to_dict(st.requirement)),
        "plan": (None if st.plan is None else _plan_to_dict(st.plan)),
        "pending_query": (None if st.pending_query is None
                          else _query_to_dict(st.pending_query)),
        "interview": [_answered_to_dict(a) for a in st.interview],
        "repair_hint": st.repair_hint,
        "feedback": [_feedback_entry_to_dict(e) for e in st.feedback.entries],
        "policy": st.policy.value,
        "report": (None if st.report is None else report_to_dict(st.report)),
    }


def _dict_to_session_state(d: dict[str, Any], src: Path) -> SessionState:
    try:
        from poor_code.domain.harness.nodes.reporter import report_from_dict
        cur = d.get("cursor")
        req = d.get("request")
        cc = d.get("understanding")
        return SessionState(
            status=SessionStatus(d["status"]),
            active_task_id=d.get("active_task_id"),
            cursor=(None if cur is None else Cursor(
                phase=Phase(cur["phase"]), current_node=cur["current_node"],
                task_id=cur.get("task_id"), attempt_id=cur.get("attempt_id"))),
            request=(None if req is None else Request(
                raw_text=req["raw_text"], kind=RequestKind(req["kind"]))),
            understanding=(None if cc is None else CodeContext(
                candidates=tuple(_dict_to_ref(r) for r in cc["candidates"]),
                confusers=tuple(_dict_to_ref(r) for r in cc["confusers"]),
                related_tests=tuple(_dict_to_ref(r) for r in cc["related_tests"]),
                search_notes=cc.get("search_notes", ""))),
            history=tuple(
                Transition(from_node=t["from_node"], to_node=t["to_node"],
                           trigger=TriggerKind(t["trigger"]), reason=t["reason"],
                           ts_iso=t["ts_iso"])
                for t in d.get("history", [])
            ),
            requirement=(None if d.get("requirement") is None
                         else _dict_to_requirement(d["requirement"])),
            plan=(None if d.get("plan") is None else _dict_to_plan(d["plan"])),
            pending_query=(None if d.get("pending_query") is None
                           else _dict_to_query(d["pending_query"])),
            interview=tuple(_dict_to_answered(a) for a in d.get("interview", [])),
            repair_hint=d.get("repair_hint"),
            feedback=FeedbackMemory(
                entries=tuple(_dict_to_feedback_entry(e) for e in d.get("feedback", []))
            ),
            policy=Policy(d.get("policy", Policy.SUPERVISED.value)),
            report=(None if d.get("report") is None else report_from_dict(d["report"])),
        )
    except (KeyError, ValueError) as e:
        raise ValueError(f"corrupt session file at {src}: {e}") from e


def _task_to_dict(t: WorkItem) -> dict[str, Any]:
    return {
        "task_id": t.task_id,
        "session_id": t.session_id,
        "raw_request": t.raw_request,
        "created_at": t.created_at.isoformat(),
    }


def _dict_to_task(d: dict[str, Any], src: Path) -> WorkItem:
    try:
        return WorkItem(
            task_id=d["task_id"],
            session_id=d["session_id"],
            raw_request=d["raw_request"],
            created_at=datetime.fromisoformat(d["created_at"]),
        )
    except (KeyError, TypeError, ValueError) as e:
        raise ValueError(f"corrupt session file at {src}: {e}") from e


def _task_state_to_dict(ts: WorkItemState) -> dict[str, Any]:
    return {
        "status": ts.status.value,
        "policies": {"implementation_locked": ts.policies.implementation_locked},
    }


def _dict_to_task_state(d: dict[str, Any], src: Path) -> WorkItemState:
    try:
        return WorkItemState(
            status=WorkItemStatus(d["status"]),
            policies=WorkItemPolicies(implementation_locked=d["policies"]["implementation_locked"]),
        )
    except (KeyError, ValueError, TypeError) as e:
        raise ValueError(f"corrupt session file at {src}: {e}") from e


class SessionStore:
    def __init__(self, root: Path) -> None:
        self._root = root

    def write_session(self, s: Session) -> None:
        _atomic_write_json(paths.session_json(self._root, s.session_id), _session_to_dict(s))

    def read_session(self, session_id: str) -> Session:
        path = paths.session_json(self._root, session_id)
        return _dict_to_session(_read_json(path), path)

    def write_session_state(self, session_id: str, st: SessionState) -> None:
        _atomic_write_json(
            paths.session_state_json(self._root, session_id),
            _session_state_to_dict(st),
        )

    def read_session_state(self, session_id: str) -> SessionState:
        path = paths.session_state_json(self._root, session_id)
        return _dict_to_session_state(_read_json(path), path)

    def write_work_item(self, t: WorkItem) -> None:
        _atomic_write_json(
            paths.work_item_request_json(self._root, t.session_id, t.task_id),
            _task_to_dict(t),
        )

    def read_work_item(self, session_id: str, task_id: str) -> WorkItem:
        path = paths.work_item_request_json(self._root, session_id, task_id)
        return _dict_to_task(_read_json(path), path)

    def write_work_item_state(self, session_id: str, task_id: str, st: WorkItemState) -> None:
        _atomic_write_json(
            paths.work_item_state_json(self._root, session_id, task_id),
            _task_state_to_dict(st),
        )

    def read_work_item_state(self, session_id: str, task_id: str) -> WorkItemState:
        path = paths.work_item_state_json(self._root, session_id, task_id)
        return _dict_to_task_state(_read_json(path), path)

    def ensure_project_map(self) -> None:
        path = paths.project_map_json(self._root)
        if path.exists():
            return
        _atomic_write_json(path, {"status": "uninitialized", "version": 1})

    def work_item_dir(self, session_id: str, task_id: str) -> Path:
        return paths.work_item_dir(self._root, session_id, task_id)

    def write_changeset(self, session_id: str, changeset: ChangeSet) -> None:
        _atomic_write_json(
            paths.changeset_json(self._root, session_id),
            _changeset_to_dict(changeset),
        )

    def write_attempt_artifacts(self, session_id: str, state: SessionState) -> None:
        """Dump per-attempt human-inspection artifacts (diff.patch, run_result.json).
        Restore authority remains state.json/plan.json; these are read-only mirrors."""
        if state.plan is None:
            return
        for task in state.plan.tasks:
            for attempt in task.attempts:
                if attempt.patch is None and attempt.run_result is None:
                    continue
                d = paths.attempt_dir(self._root, session_id, task.id, attempt.id)
                d.mkdir(parents=True, exist_ok=True)
                if attempt.patch is not None:
                    (d / "diff.patch").write_text(attempt.patch.diff, encoding="utf-8")
                if attempt.run_result is not None:
                    _atomic_write_json(
                        d / "run_result.json",
                        _validation_result_to_dict(attempt.run_result))
