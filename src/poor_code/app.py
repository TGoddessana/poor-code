from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from textual.app import App
from textual.reactive import reactive

from poor_code.domain.agent import Agent
from poor_code.domain.harness.sink import TurnSink
from poor_code.domain.harness.trace import TraceSink
from poor_code.domain.session import paths as session_paths
from poor_code.domain.project_map import ProjectMapBuilder, ProjectMapStore
from poor_code.domain.session.models import (
    Cursor, Phase, Request, RequestKind, SessionState, UserResponse,
)
from poor_code.infra import paths
from poor_code.messages import (
    ProjectMapBuildFailed,
    ProjectMapBuildFinished,
    ProjectMapBuildProgress,
    ProjectMapBuildStarted,
    TurnEnded,
    TurnFailed,
    TurnStarted,
)
from poor_code.provider.client import LLMClient
from poor_code.slash.dispatcher import SlashDispatcher
from poor_code.ui.narrator import StaticNarrator
from poor_code.ui.screens.chat import ChatScreen
from poor_code.ui.store import (
    AnswerSubmitted, AppState, ProviderChanged, PromptSubmitted,
    SteeringSubmitted, Store, TurnInterrupted,
)


def _is_double_tap(now: float, last: float | None, window: float = 2.0) -> bool:
    """True when `now` falls within `window` seconds of a prior press `last`."""
    return last is not None and (now - last) <= window


def _is_smart_driver_query(state: SessionState | None) -> bool:
    q = None if state is None else state.pending_query
    return q is not None and q.resolves == "smart_driver_hitl"


def _smart_driver_enabled(driver: Any) -> bool:
    runtime = getattr(driver, "_runtime", None)
    return bool(
        runtime is not None
        and getattr(runtime, "smart_enabled", False)
        and getattr(runtime, "advisor", None) is not None
    )


def classify_conclusion(
    final, *, cancelled: bool = False, error: str | None = None,
    escalate_detail: str | None = None,
) -> tuple[str, str]:
    """Why this drive segment ended. Pure: derived from final state + flags.
    Returns (reason, detail)."""
    if error is not None:
        return "error", error
    if cancelled:
        return "cancelled", ""
    if getattr(final, "pending_query", None) is not None:
        pq = final.pending_query
        return "suspended", f"awaiting input: {pq.prompt}"
    if getattr(final, "report", None) is not None:
        outcome = getattr(getattr(final.report, "outcome", None), "value", "?")
        return "completed", f"report ({outcome})"
    if escalate_detail:
        return "escalated", escalate_detail
    if getattr(final, "plan", None) is not None:
        return "parked", "plan ready"
    node = final.cursor.current_node if getattr(final, "cursor", None) else "?"
    return "parked", f"node '{node}' not reached"


def _plan_signature(plan) -> tuple[str, ...]:
    """Stable enough UI signature for suppressing duplicate PlanReady events."""
    lines: list[str] = [f"plan_md:{getattr(plan, 'plan_md', '')}"]
    for slot in getattr(plan, "file_plan", ()):
        lines.append(f"file:{slot.path}:{slot.responsibility}")
    for dep in getattr(plan, "deps", ()):
        lines.append(f"dep:{dep.task_id}:{dep.depends_on}")
    for task in getattr(plan, "tasks", ()):
        scope = getattr(task, "edit_scope", None)
        editable = ",".join(getattr(scope, "editable", ()) if scope is not None else ())
        readonly = ",".join(getattr(scope, "readonly", ()) if scope is not None else ())
        forbidden = ",".join(getattr(scope, "forbidden", ()) if scope is not None else ())
        step_sig = ",".join(
            f"{s.id}:{s.kind}:{s.file}:{s.anchor}:{s.run}:{s.expected}"
            for s in getattr(task, "steps", ())
        )
        lines.append(
            f"task:{task.id}:{task.title}:{task.purpose}:{task.description}:"
            f"{editable}:{readonly}:{forbidden}:{task.how_to_validate}:{step_sig}"
        )
    return tuple(lines)


class PoorCodeApp(App):
    CSS_PATH = "ui/styles/app.tcss"
    BINDINGS = [
        ("ctrl+q", "quit", "Quit"),
        # Ctrl+C never cancels work — it is a two-step exit confirm (first press
        # shows a hint, a second press within the window quits). Interrupting a
        # turn is Esc's job (see action_interrupt).
        ("ctrl+c", "ctrl_c", "Quit (×2)"),
        # Esc: immediate interrupt of the in-flight turn for human-in-the-loop
        # steering; no-op when idle.
        ("escape", "interrupt", "Interrupt"),
        ("ctrl+i", "open_state", "State"),
    ]

    app_state: reactive[AppState] = reactive(AppState(), layout=False)

    def __init__(
        self,
        agent: Agent,
        make_driver: Callable[..., Any],
        slash: SlashDispatcher | None = None,
        project_map_builder: ProjectMapBuilder | None = None,
        session: Any = None,
    ) -> None:
        super().__init__()
        self.store = Store(AppState(cwd=str(Path.cwd())))
        self._session = session
        self.agent = agent
        self._make_driver = make_driver
        self._live_state: SessionState | None = None
        self._harness_driver = make_driver(agent.llm, self._on_checkpoint)
        self.slash = slash or SlashDispatcher()
        self._cancel = asyncio.Event()
        self._project_map_builder = project_map_builder
        self._project_map_store = ProjectMapStore()
        self._harness_state: SessionState | None = None
        self._turn_id: str | None = None
        self._turn_started: float = 0.0
        self._narrator = StaticNarrator()
        self._last_ctrl_c: float | None = None
        self._interrupted: bool = False
        self._announced_plan: tuple[str | None, tuple[str, ...]] | None = None

    def on_mount(self) -> None:
        self.store.subscribe(lambda s: setattr(self, "app_state", s))
        self.app_state = self.store.state
        self._dispatch_provider(self.agent.llm)
        self.push_screen(ChatScreen())
        if self._project_map_builder is not None:
            self.run_worker(self._build_project_map(), group="project_map", exclusive=True)

    async def _build_project_map(self) -> None:
        builder = self._project_map_builder
        if builder is None:
            return
        cwd = Path.cwd()
        store = self._project_map_store
        loop = asyncio.get_running_loop()

        def progress(bp):  # called from executor thread
            self.call_from_thread(
                self.store.dispatch,
                ProjectMapBuildProgress(
                    files_processed=bp.files_processed,
                    files_total=bp.files_total,
                ),
            )

        # Pre-build dispatch: total isn't known until discovery runs; emit
        # Started with a sentinel 0 and let the first Progress event correct it.
        self.store.dispatch(ProjectMapBuildStarted(files_total=0))

        t0 = time.monotonic()
        try:
            project_map = await loop.run_in_executor(
                None, lambda: builder.build(cwd, progress)
            )
            store.write(project_map, paths.config_dir(cwd))
        except Exception as e:
            self.store.dispatch(ProjectMapBuildFailed(error=f"{type(e).__name__}: {e}"))
            return

        duration_ms = int((time.monotonic() - t0) * 1000)
        self.store.dispatch(
            ProjectMapBuildFinished(
                files_total=len(project_map.files),
                parse_error_count=len(project_map.parse_errors),
                duration_ms=duration_ms,
            )
        )

    def _dispatch_provider(self, llm: Any) -> None:
        if isinstance(llm, LLMClient):
            self.store.dispatch(
                ProviderChanged(provider_name=llm.provider_name or None, model=llm.model)
            )
        else:
            self.store.dispatch(ProviderChanged(provider_name=None, model=None))

    def submit(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        if self.slash.dispatch(text, ctx=self):
            return
        self._cancel = asyncio.Event()
        # Capture-then-clear: an interrupt sets _interrupted=True; consume it here so
        # it can never leak into a later, unrelated turn regardless of which branch runs.
        was_interrupted = self._interrupted
        self._interrupted = False
        parked = self._harness_state
        if was_interrupted and parked is not None:
            # steering-resume branch — user intervened mid-turn; inject the message
            # as a directive and resume from the preserved cursor (NOT the router).
            if _smart_driver_enabled(self._harness_driver):
                # Preserve the parked query for Smart Driver's briefing so utterances like
                # "이 질문이 아닌데?" can be understood as objections to that query.
                state = parked.with_steering(text)
            else:
                state = parked.without_pending_query().with_steering(text)
            self.store.dispatch(SteeringSubmitted(turn_id=self._turn_id, text=text))
        elif _is_smart_driver_query(parked):
            # A Smart Driver confirmation answer is itself a HITL utterance: "continue",
            # "no, change X", or a fresh pivot all need to be classified by the advisor.
            state = parked.without_pending_query().with_steering(text)
            self.store.dispatch(SteeringSubmitted(turn_id=self._turn_id, text=text))
        elif parked is not None and parked.pending_query is not None:
            # answer branch — continue the same long turn
            resp = UserResponse(query_id=parked.pending_query.id, answer=text)
            state = parked.with_user_response(resp)
            self.store.dispatch(AnswerSubmitted(turn_id=self._turn_id, answer=text))
        else:
            # new-request branch — open a fresh turn
            cmd_id = uuid.uuid4().hex
            turn_id = uuid.uuid4().hex
            self.store.dispatch(PromptSubmitted(cmd_id=cmd_id, user_text=text))
            self.store.dispatch(TurnStarted(cmd_id=cmd_id, turn_id=turn_id))
            self._turn_id = turn_id
            self._turn_started = time.monotonic()
            state = SessionState(
                cursor=Cursor(phase=Phase.ROUTING, current_node="router"),
                request=Request(raw_text=text, kind=RequestKind.ENGINEERING),
            )
        self._live_state = state
        self.run_worker(self._drive(state), group="turn", exclusive=True)

    async def _drive(self, state: SessionState) -> None:
        sink = TurnSink(
            self._turn_id, self.store.dispatch, narrator=self._narrator,
            trace=self._make_trace_sink(self._turn_id))
        model = getattr(self.agent.llm, "model", "") or ""
        try:
            final = await self._harness_driver.run(state, self._cancel, sink=sink)
        except asyncio.CancelledError:
            if self._interrupted:
                # User interrupt: action_interrupt already preserved _harness_state
                # and dispatched TurnInterrupted. Conclude the trace and re-raise so
                # the worker finishes cancelling cleanly.
                sink.turn_concluded("interrupted", "")
                raise
            sink.turn_concluded(*classify_conclusion(state, cancelled=True))
            self.store.dispatch(TurnFailed(turn_id=self._turn_id, error="cancelled"))
            self._harness_state = None
            return
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            sink.turn_concluded(*classify_conclusion(state, error=err))
            self.store.dispatch(TurnFailed(turn_id=self._turn_id, error=err))
            self._harness_state = None
            return
        if self._cancel.is_set():
            if self._interrupted:
                sink.turn_concluded("interrupted", "")
                return  # state preserved by action_interrupt; TurnInterrupted dispatched
            sink.turn_concluded("cancelled", "")
            self.store.dispatch(TurnFailed(turn_id=self._turn_id, error="cancelled"))
            self._harness_state = None
            return
        self._harness_state = final
        escalate = getattr(self._harness_driver, "last_escape", None)
        escalate_detail = (escalate.query or escalate.hint) if escalate is not None else None
        sink.turn_concluded(*classify_conclusion(final, escalate_detail=escalate_detail))
        if final.pending_query is not None:
            if final.pending_query.id == "confirm_plan" and final.plan is not None:
                self._plan_ready_once(sink, final.plan)
            sink.query_raised(final.pending_query)
            return  # turn stays open; reducer set awaiting_input
        if final.plan is not None:
            self._plan_ready_once(sink, final.plan)
        if final.report is not None:
            sink.report_ready(final.report)
        self.store.dispatch(TurnEnded(
            turn_id=self._turn_id,
            duration_sec=time.monotonic() - self._turn_started,
            model=model,
        ))
        self._harness_state = None

    def _plan_ready_once(self, sink: TurnSink, plan) -> None:
        key = (self._turn_id, _plan_signature(plan))
        if self._announced_plan == key:
            return
        sink.plan_ready(plan)
        self._announced_plan = key

    def _make_trace_sink(self, turn_id: str) -> TraceSink | None:
        if self._session is None:
            return None
        try:
            sid = self._session.active_session().session_id
        except Exception:
            return None
        root = paths.config_dir(Path.cwd())
        return TraceSink(session_paths.turn_trace_jsonl(root, sid, turn_id))

    def answer_query(self, answer: str, chosen_option: str | None = None) -> None:
        """Answer the parked query (used by the inline QueryWidget). Mirrors the
        answer branch of submit() but carries chosen_option."""
        parked = self._harness_state
        if parked is None or parked.pending_query is None:
            return
        self._cancel = asyncio.Event()
        self._interrupted = False
        if _is_smart_driver_query(parked):
            state = parked.without_pending_query().with_steering(answer)
            self.store.dispatch(SteeringSubmitted(turn_id=self._turn_id, text=answer))
            self._live_state = state
            self.run_worker(self._drive(state), group="turn", exclusive=True)
            return
        resp = UserResponse(
            query_id=parked.pending_query.id, answer=answer, chosen_option=chosen_option)
        state = parked.with_user_response(resp)
        self.store.dispatch(AnswerSubmitted(turn_id=self._turn_id, answer=answer))
        self._live_state = state
        self.run_worker(self._drive(state), group="turn", exclusive=True)

    def set_llm(self, llm: Any) -> None:
        self.agent.llm = llm
        self._harness_driver = self._make_driver(llm, self._on_checkpoint)
        self._dispatch_provider(llm)

    def _on_checkpoint(self, state: SessionState) -> None:
        """Driver on_step hook: capture the latest live SessionState so the
        StateInspector can show in-flight context. Runs on the UI event loop
        (drive is a coroutine, not a thread) → direct assignment is safe."""
        self._live_state = state

    def action_ctrl_c(self) -> None:
        now = time.monotonic()
        if _is_double_tap(now, self._last_ctrl_c):
            self.exit()
            return
        self._last_ctrl_c = now
        self.notify("Press Ctrl+C again to exit", timeout=2.0)

    def action_interrupt(self) -> None:
        st = self.app_state
        if not st.is_processing:
            return  # idle: Esc is a no-op (use Ctrl+C ×2 or Ctrl+Q to quit)
        # Immediate stop: cancel the running turn worker so an in-flight LLM/tool
        # call is interrupted now, not at the next node boundary. _cancel.set()
        # also covers nodes that poll the event.
        self._cancel.set()
        self.workers.cancel_group(self, "turn")
        # Preserve the last node-boundary checkpoint so the next message resumes
        # from cursor.current_node instead of restarting at the router.
        parked_on_query = (
            st.awaiting_input
            and self._harness_state is not None
            and self._harness_state.pending_query is not None
        )
        if not parked_on_query:
            self._harness_state = self._live_state
        self._interrupted = True
        self.store.dispatch(TurnInterrupted(turn_id=self._turn_id))

    def action_open_state(self) -> None:
        from poor_code.ui.screens.state_inspector import StateInspector
        if isinstance(self.screen, StateInspector):
            self.pop_screen()
        else:
            self.push_screen(StateInspector())
