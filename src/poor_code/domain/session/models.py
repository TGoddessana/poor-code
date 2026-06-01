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


class TaskStatus(str, Enum):
    PENDING = "pending"
    DONE = "done"
    ABORTED = "aborted"
    # S2~S9 add their phase values (MAPPING, INTERVIEWING, ...) when introducing those cycles.


@dataclass(frozen=True, slots=True)
class Policies:
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

    def with_request(self, request: Request) -> "SessionState":
        return replace(self, request=request)

    def with_understanding(self, cc: CodeContext) -> "SessionState":
        return replace(self, understanding=cc)

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
class Task:
    task_id: str
    session_id: str
    raw_request: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class TaskState:
    status: TaskStatus = TaskStatus.PENDING
    policies: Policies = field(default_factory=Policies)


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


class Phase(str, Enum):
    ROUTING = "routing"
    LOCATING = "locating"
    INTERVIEWING = "interviewing"
    # S5~ 가 PLANNING/… 추가


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
