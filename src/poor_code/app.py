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
    AnswerSubmitted, AppState, ProviderChanged, PromptSubmitted, Store,
)


class PoorCodeApp(App):
    CSS_PATH = "ui/styles/app.tcss"
    BINDINGS = [
        ("ctrl+q", "quit", "Quit"),
        ("ctrl+c", "cancel_or_quit", "Cancel/Quit"),
    ]

    app_state: reactive[AppState] = reactive(AppState(), layout=False)

    def __init__(
        self,
        agent: Agent,
        make_driver: Callable[[Any], Any],
        slash: SlashDispatcher | None = None,
        project_map_builder: ProjectMapBuilder | None = None,
    ) -> None:
        super().__init__()
        self.store = Store(AppState(cwd=str(Path.cwd())))
        self.agent = agent
        self._make_driver = make_driver
        self._harness_driver = make_driver(agent.llm)
        self.slash = slash or SlashDispatcher()
        self._cancel = asyncio.Event()
        self._project_map_builder = project_map_builder
        self._project_map_store = ProjectMapStore()
        self._harness_state: SessionState | None = None
        self._turn_id: str | None = None
        self._turn_started: float = 0.0
        self._narrator = StaticNarrator()

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
        parked = self._harness_state
        if parked is not None and parked.pending_query is not None:
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
        self.run_worker(self._drive(state), group="turn", exclusive=True)

    async def _drive(self, state: SessionState) -> None:
        sink = TurnSink(self._turn_id, self.store.dispatch, narrator=self._narrator)
        model = getattr(self.agent.llm, "model", "") or ""
        try:
            final = await self._harness_driver.run(state, self._cancel, sink=sink)
        except asyncio.CancelledError:
            self.store.dispatch(TurnFailed(turn_id=self._turn_id, error="cancelled"))
            self._harness_state = None
            return
        except Exception as e:
            self.store.dispatch(TurnFailed(
                turn_id=self._turn_id, error=f"{type(e).__name__}: {e}"))
            self._harness_state = None
            return
        if self._cancel.is_set():
            self.store.dispatch(TurnFailed(turn_id=self._turn_id, error="cancelled"))
            self._harness_state = None
            return
        self._harness_state = final
        if final.pending_query is not None:
            sink.query_raised(final.pending_query)
            return  # turn stays open; reducer set awaiting_input
        if final.plan is not None:
            sink.plan_ready(final.plan)
        if final.report is not None:
            sink.report_ready(final.report)
        self.store.dispatch(TurnEnded(
            turn_id=self._turn_id,
            duration_sec=time.monotonic() - self._turn_started,
            model=model,
        ))
        self._harness_state = None

    def set_llm(self, llm: Any) -> None:
        self.agent.llm = llm
        self._harness_driver = self._make_driver(llm)
        self._dispatch_provider(llm)

    def action_cancel_or_quit(self) -> None:
        if self.app_state.is_processing:
            self._cancel.set()
        else:
            self.exit()
