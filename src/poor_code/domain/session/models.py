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
class FeedbackEntry:
    failure_type: str
    symptom: str
    prevention_hint: str
    task_ref: str | None = None


@dataclass(frozen=True, slots=True)
class FeedbackMemory:
    entries: tuple[FeedbackEntry, ...] = ()


class Policy(str, Enum):
    SUPERVISED = "supervised"   # TUI default — suspend on query
    FULL_AUTO = "full_auto"     # headless — auto-answer, never suspend
    PARANOID = "paranoid"       # enum only; tool-prompt behavior deferred


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
    acceptance: "AcceptanceSpec | None" = None
    pending_query: "Query | None" = None
    interview: "tuple[AnsweredQuery, ...]" = ()
    repair_hint: str | None = None
    feedback: FeedbackMemory = field(default_factory=FeedbackMemory)
    report: "Report | None" = None
    policy: Policy = Policy.SUPERVISED

    def with_request(self, request: Request) -> "SessionState":
        return replace(self, request=request)

    def with_understanding(self, cc: CodeContext) -> "SessionState":
        return replace(self, understanding=cc)

    def with_requirement(self, r: "Requirement") -> "SessionState":
        return replace(self, requirement=r)

    def with_plan(self, p: "Plan") -> "SessionState":
        return replace(self, plan=p)

    def with_acceptance(self, spec: "AcceptanceSpec") -> "SessionState":
        return replace(self, acceptance=spec)

    def with_pending_query(self, q: "Query") -> "SessionState":
        return replace(self, pending_query=q)

    def with_repair_hint(self, hint: str | None) -> "SessionState":
        return replace(self, repair_hint=hint)

    def with_feedback_entry(self, entry: "FeedbackEntry") -> "SessionState":
        return replace(
            self,
            feedback=replace(self.feedback, entries=self.feedback.entries + (entry,)),
        )

    def with_report(self, r: "Report") -> "SessionState":
        return replace(self, report=r)

    def with_policy(self, p: "Policy") -> "SessionState":
        return replace(self, policy=p)

    def _with_task(self, task_id: str, **changes) -> "SessionState":
        assert self.plan is not None, "no plan to update tasks in"
        if not any(t.id == task_id for t in self.plan.tasks):
            raise ValueError(f"task {task_id!r} not found in plan")
        tasks = tuple(
            replace(t, **changes) if t.id == task_id else t
            for t in self.plan.tasks
        )
        return replace(self, plan=replace(self.plan, tasks=tasks))

    def with_active_task(self, task_id: str) -> "SessionState":
        st = self._with_task(task_id, status=TaskStatus.ACTIVE)
        st = replace(st, active_task_id=task_id)
        if st.cursor is None:
            return st
        return replace(st, cursor=replace(st.cursor, task_id=task_id))

    def with_task_status(self, task_id: str, status: "TaskStatus") -> "SessionState":
        return self._with_task(task_id, status=status)

    def append_attempt(self, task_id: str, attempt: "Attempt") -> "SessionState":
        assert self.plan is not None, "no plan to append attempts to"
        if not any(t.id == task_id for t in self.plan.tasks):
            raise ValueError(f"task {task_id!r} not found in plan")
        tasks = tuple(
            replace(t, attempts=t.attempts + (attempt,)) if t.id == task_id else t
            for t in self.plan.tasks
        )
        st = replace(self, plan=replace(self.plan, tasks=tasks))
        if st.cursor is None:
            return st
        return replace(st, cursor=replace(st.cursor, attempt_id=attempt.id))

    def update_attempt(self, task_id: str, attempt_id: str, **changes) -> "SessionState":
        assert self.plan is not None, "no plan to update attempts in"
        task = next((t for t in self.plan.tasks if t.id == task_id), None)
        if task is None:
            raise ValueError(f"task {task_id!r} not found in plan")
        if not any(a.id == attempt_id for a in task.attempts):
            raise ValueError(f"attempt {attempt_id!r} not found in task {task_id!r}")

        def upd(t):
            if t.id != task_id:
                return t
            atts = tuple(
                replace(a, **changes) if a.id == attempt_id else a
                for a in t.attempts
            )
            return replace(t, attempts=atts)

        tasks = tuple(upd(t) for t in self.plan.tasks)
        return replace(self, plan=replace(self.plan, tasks=tasks))

    def with_task_context(self, task_id: str, context: "TaskContext") -> "SessionState":
        return self._with_task(task_id, context=context)

    def upsert_attempt(self, task_id: str, attempt: "Attempt") -> "SessionState":
        """Append the attempt, or replace the existing one with the same id
        (in-place adversarial refinement). Sets cursor.attempt_id either way."""
        assert self.plan is not None, "no plan to upsert attempts in"
        task = next((t for t in self.plan.tasks if t.id == task_id), None)
        if task is None:
            raise ValueError(f"task {task_id!r} not found in plan")
        if any(a.id == attempt.id for a in task.attempts):
            attempts = tuple(attempt if a.id == attempt.id else a for a in task.attempts)
        else:
            attempts = task.attempts + (attempt,)
        tasks = tuple(replace(t, attempts=attempts) if t.id == task_id else t
                      for t in self.plan.tasks)
        st = replace(self, plan=replace(self.plan, tasks=tasks))
        if st.cursor is None:
            return st
        return replace(st, cursor=replace(st.cursor, attempt_id=attempt.id))

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
        cur_task_id = self.cursor.task_id if self.cursor is not None else None
        cur_attempt_id = self.cursor.attempt_id if self.cursor is not None else None
        return replace(
            self,
            cursor=Cursor(phase=phase, current_node=node,
                          task_id=cur_task_id, attempt_id=cur_attempt_id),
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


class GroundingStatus(str, Enum):
    """Disambiguates an empty `CodeContext.candidates`. Only consulted when
    candidates is empty; when candidates is non-empty the gate advances on that."""
    NOT_FOUND = "not_found"    # searched, expected to find code, but failed (real failure)
    GREENFIELD = "greenfield"  # nothing to ground (create-from-scratch); empty is expected


@dataclass(frozen=True, slots=True)
class FileExcerpt:
    """A real file body the Explorer read, carried verbatim into CodeContext so
    downstream nodes see ground truth (not model-retyped text). `truncated` marks
    a head-only slice of a large file."""
    path: str
    text: str
    truncated: bool = False


@dataclass(frozen=True, slots=True)
class CodeContext:
    candidates: tuple[CodeRef, ...] = ()
    confusers: tuple[CodeRef, ...] = ()
    related_tests: tuple[CodeRef, ...] = ()
    search_notes: str = ""        # explorer 자기진단(빈손일 때 채움)
    grounding: GroundingStatus = GroundingStatus.NOT_FOUND  # 빈손 해석에만 의미
    summary: str = ""             # explorer 합성 브리핑 (한 단락)
    excerpts: tuple[FileExcerpt, ...] = ()  # explorer가 실제로 읽은 본문
    environment: str = ""         # explorer가 1회 probe한 OS/런타임/툴체인 스냅샷


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


@dataclass(frozen=True, slots=True)
class AcceptanceCheck:
    """One runnable acceptance check: exit 0 == criterion satisfied."""
    criterion: str
    command: str
    rationale: str = ""


@dataclass(frozen=True, slots=True)
class AcceptanceSpec:
    """The global, plan-independent definition of 'done' (acceptance_oracle output)."""
    checks: tuple[AcceptanceCheck, ...] = ()


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


class AttemptStatus(str, Enum):
    ACTIVE = "active"
    DONE = "done"
    ABANDONED = "abandoned"


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """run_result — pass/fail 구속 ★. validation_runner(코드)만 생성."""
    command: str
    exit_code: int
    passed: bool
    output: str = ""


@dataclass(frozen=True, slots=True)
class ChangeRecord:
    """직접변경 결과. diff는 git에서 사후추출."""
    files: tuple[str, ...] = ()
    diff: str = ""


@dataclass(frozen=True, slots=True)
class ChangeSet:
    aggregate_diff: str = ""
    per_task: tuple[tuple[str, str], ...] = ()   # (task_id, diff)


class ReportOutcome(str, Enum):
    SUCCEEDED = "succeeded"
    ABANDONED = "abandoned"


@dataclass(frozen=True, slots=True)
class TaskReport:
    task_id: str
    title: str
    status: TaskStatus
    attempts: int = 0


@dataclass(frozen=True, slots=True)
class Report:
    outcome: ReportOutcome
    tasks: tuple[TaskReport, ...] = ()
    global_validation_passed: bool = False
    changeset: ChangeSet | None = None
    summary: str = ""


@dataclass(frozen=True, slots=True)
class SelectedTask:
    """task_selector → Driver 제어 신호. task_selector가 None을 반환하면 'done' 분기."""
    # NOTE: no store serializer yet — added in Plan 2 when first persisted.
    task_id: str


@dataclass(frozen=True, slots=True)
class TaskCompleted:
    """completion_gate → Driver 제어 신호: 이 Task가 검증 통과로 완료됨.
    control-only — store에 직렬화하지 않음(상태는 Task.status/Attempt.status로 영속)."""
    task_id: str
    attempt_id: str


@dataclass(frozen=True, slots=True)
class Attempt:
    """한 번의 구현-검증 시도. 실행층의 안쪽 사이클 단위."""
    id: str
    patch: ChangeRecord | None = None             # ~생성~
    assumptions: tuple[str, ...] = ()
    validator_verdict: Verdict | None = None      # ~생성~ 자문(권한X)
    run_result: ValidationResult | None = None    # 구속 ★ runner만
    gate_verdict: Verdict | None = None
    adversarial_rounds: int = 0                   # 적대적 캡 카운터
    status: AttemptStatus = AttemptStatus.ACTIVE


class Phase(str, Enum):
    ROUTING = "routing"
    LOCATING = "locating"
    INTERVIEWING = "interviewing"
    PLANNING = "planning"
    IMPLEMENTING = "implementing"
    FINALIZING = "finalizing"


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
    ACCEPTANCE = "acceptance"


@dataclass(frozen=True, slots=True)
class Verdict:
    kind: VerdictKind
    layer: Layer | None = None
    hint: str | None = None
    query: str | None = None
