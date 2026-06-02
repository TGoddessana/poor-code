"""Domain models for session/task lifecycle. See CONTRACT.md."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum
from pathlib import Path


class SessionStatus(str, Enum):
    READY = "ready"
    BUSY = "busy"
    CLOSED = "closed"


class WorkItemStatus(str, Enum):
    PENDING = "pending"
    DONE = "done"
    ABORTED = "aborted"
    # S2~S9 add their phase values (MAPPING, INTERVIEWING, ...) when introducing those cycles.


@dataclass(frozen=True, slots=True)
class WorkItemPolicies:
    implementation_locked: bool = True


@dataclass(frozen=True, slots=True)
class Session:
    session_id: str
    cwd: Path
    created_at: datetime
    parent_session_id: str | None = None
    version: int = 1


@dataclass(frozen=True, slots=True)
class SessionState:
    status: SessionStatus = SessionStatus.READY
    active_task_id: str | None = None
    cursor: Cursor | None = None
    request: Request | None = None
    understanding: CodeContext | None = None
    history: tuple[Transition, ...] = ()
    requirement: "Requirement | None" = None
    plan: "Plan | None" = None
    pending_query: "Query | None" = None
    interview: "tuple[AnsweredQuery, ...]" = ()
    repair_hint: str | None = None

    def with_request(self, request: Request) -> "SessionState":
        return replace(self, request=request)

    def with_understanding(self, cc: CodeContext) -> "SessionState":
        return replace(self, understanding=cc)

    def with_requirement(self, r: "Requirement") -> "SessionState":
        return replace(self, requirement=r)

    def with_plan(self, p: "Plan") -> "SessionState":
        return replace(self, plan=p)

    def with_pending_query(self, q: "Query") -> "SessionState":
        return replace(self, pending_query=q)

    def with_repair_hint(self, hint: str | None) -> "SessionState":
        return replace(self, repair_hint=hint)

    def with_user_response(self, resp: "UserResponse") -> "SessionState":
        assert self.pending_query is not None, "no pending query to answer"
        if resp.query_id != self.pending_query.id:
            raise ValueError(
                f"response query_id {resp.query_id!r} != pending {self.pending_query.id!r}"
            )
        answered = AnsweredQuery(query=self.pending_query, response=resp)
        return replace(self, interview=self.interview + (answered,), pending_query=None)

    def advancing_to(
        self, *, node: str, phase: Phase, trigger: TriggerKind, reason: str, ts_iso: str
    ) -> "SessionState":
        prev = self.cursor.current_node if self.cursor else ""
        tr = Transition(from_node=prev, to_node=node, trigger=trigger, reason=reason, ts_iso=ts_iso)
        return replace(
            self,
            cursor=Cursor(phase=phase, current_node=node),
            history=self.history + (tr,),
        )


@dataclass(frozen=True, slots=True)
class WorkItem:
    task_id: str
    session_id: str
    raw_request: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class WorkItemState:
    status: WorkItemStatus = WorkItemStatus.PENDING
    policies: WorkItemPolicies = field(default_factory=WorkItemPolicies)


# ----- harness value objects (graph cycle) -----

class RequestKind(str, Enum):
    ENGINEERING = "engineering"
    LIGHTWEIGHT = "lightweight"


@dataclass(frozen=True, slots=True)
class Request:
    raw_text: str
    kind: RequestKind


@dataclass(frozen=True, slots=True)
class CodeRef:
    """ProjectMap을 가리키는 타입 포인터. symbol=None이면 파일 전체."""
    file: str
    symbol: str | None = None
    lineno: int | None = None


@dataclass(frozen=True, slots=True)
class CodeContext:
    candidates: tuple[CodeRef, ...] = ()
    confusers: tuple[CodeRef, ...] = ()
    related_tests: tuple[CodeRef, ...] = ()
    search_notes: str = ""        # explorer 자기진단(빈손일 때 채움)


class QueryKind(str, Enum):
    CLARIFY = "clarify"
    CHOOSE = "choose"
    APPROVE = "approve"
    CONFIRM = "confirm"


@dataclass(frozen=True, slots=True)
class Query:
    """사용자에게 묻는 1급 객체 (§19). id는 노드가 결정론적으로 부여."""
    id: str
    kind: QueryKind
    prompt: str
    context: str | None = None
    options: tuple[str, ...] = ()      # CHOOSE 선택지
    resolves: str | None = None        # 어떤 Requirement 슬롯을 채우나(선택)
    rationale: str | None = None       # 이 질문이 왜 구현을 바꾸나


@dataclass(frozen=True, slots=True)
class UserResponse:
    query_id: str
    answer: str
    chosen_option: str | None = None


@dataclass(frozen=True, slots=True)
class AnsweredQuery:
    query: Query
    response: UserResponse


@dataclass(frozen=True, slots=True)
class Requirement:
    """§10 [구속] — Interviewer 산출. 모델 추측(CodeContext)과 달리 사용자 확정."""
    summary: str
    acceptance: tuple[str, ...] = ()
    out_of_scope: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    open_questions: tuple[str, ...] = ()


class TaskStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    DONE = "done"
    BLOCKED = "blocked"
    ABANDONED = "abandoned"


@dataclass(frozen=True, slots=True)
class EditScope:
    editable: tuple[str, ...] = ()
    readonly: tuple[str, ...] = ()
    forbidden: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TaskContext:
    refs: tuple[CodeRef, ...] = ()
    snippet: str | None = None


@dataclass(frozen=True, slots=True)
class Attempt:
    status: TaskStatus = TaskStatus.PENDING


@dataclass(frozen=True, slots=True)
class Task:
    id: str
    title: str
    purpose: str
    description: str = ""
    edit_scope: EditScope = field(default_factory=EditScope)
    how_to_validate: str = ""
    status: TaskStatus = TaskStatus.PENDING
    context: TaskContext | None = None
    attempts: tuple[Attempt, ...] = ()


@dataclass(frozen=True, slots=True)
class Dependency:
    task_id: str
    depends_on: str


@dataclass(frozen=True, slots=True)
class Plan:
    tasks: tuple[Task, ...] = ()
    deps: tuple[Dependency, ...] = ()


class Phase(str, Enum):
    ROUTING = "routing"
    LOCATING = "locating"
    INTERVIEWING = "interviewing"
    PLANNING = "planning"
    # S7~ 가 IMPLEMENTING/… 추가


class TriggerKind(str, Enum):
    FORWARD = "forward"
    GATE = "gate"
    USER = "user"
    ESCALATE = "escalate"


@dataclass(frozen=True, slots=True)
class Cursor:
    phase: Phase
    current_node: str
    task_id: str | None = None
    attempt_id: str | None = None


@dataclass(frozen=True, slots=True)
class Transition:
    from_node: str
    to_node: str
    trigger: TriggerKind
    reason: str
    ts_iso: str  # isoformat; 호출부에서 datetime.now(UTC).isoformat()


class VerdictKind(str, Enum):
    ADVANCE = "advance"
    REPAIR = "repair"
    ESCALATE = "escalate"


class Layer(str, Enum):
    IMPLEMENTATION = "implementation"
    PLAN = "plan"
    UNDERSTANDING = "understanding"


@dataclass(frozen=True, slots=True)
class Verdict:
    kind: VerdictKind
    layer: Layer | None = None
    hint: str | None = None
    query: str | None = None
