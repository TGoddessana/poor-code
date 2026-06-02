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
    CodeContext,
    CodeRef,
    Cursor,
    Phase,
    WorkItemPolicies,
    Query,
    QueryKind,
    Request,
    RequestKind,
    Requirement,
    Session,
    SessionState,
    SessionStatus,
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
            }
        ),
        "history": [
            {"from_node": t.from_node, "to_node": t.to_node,
             "trigger": t.trigger.value, "reason": t.reason, "ts_iso": t.ts_iso}
            for t in st.history
        ],
        "requirement": (None if st.requirement is None
                        else _requirement_to_dict(st.requirement)),
        "pending_query": (None if st.pending_query is None
                          else _query_to_dict(st.pending_query)),
        "interview": [_answered_to_dict(a) for a in st.interview],
    }


def _dict_to_session_state(d: dict[str, Any], src: Path) -> SessionState:
    try:
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
                related_tests=tuple(_dict_to_ref(r) for r in cc["related_tests"]))),
            history=tuple(
                Transition(from_node=t["from_node"], to_node=t["to_node"],
                           trigger=TriggerKind(t["trigger"]), reason=t["reason"],
                           ts_iso=t["ts_iso"])
                for t in d.get("history", [])
            ),
            requirement=(None if d.get("requirement") is None
                         else _dict_to_requirement(d["requirement"])),
            pending_query=(None if d.get("pending_query") is None
                           else _dict_to_query(d["pending_query"])),
            interview=tuple(_dict_to_answered(a) for a in d.get("interview", [])),
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
