from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from textual.app import App
from textual.reactive import reactive

from poor_code.domain.agent import Agent
from poor_code.messages import SendPrompt
from poor_code.slash.dispatcher import SlashDispatcher
from poor_code.ui.screens.welcome import WelcomeScreen
from poor_code.ui.store import AppState, PromptSubmitted, Store


class PoorCodeApp(App):
    CSS_PATH = "ui/styles/app.tcss"
    BINDINGS = [
        ("ctrl+q", "quit", "Quit"),
        ("ctrl+c", "cancel_or_quit", "Cancel/Quit"),
    ]

    app_state: reactive[AppState] = reactive(AppState(), layout=False)

    def __init__(self, agent: Agent, slash: SlashDispatcher | None = None) -> None:
        super().__init__()
        self.store = Store(AppState(cwd=str(Path.cwd())))
        self.agent = agent
        self.slash = slash or SlashDispatcher()
        self._cancel = asyncio.Event()

    def on_mount(self) -> None:
        self.store.subscribe(lambda s: setattr(self, "app_state", s))
        self.app_state = self.store.state
        self.push_screen(WelcomeScreen())

    def submit(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        if self.slash.dispatch(text, ctx=self):
            return
        cmd = SendPrompt(text)
        self.store.dispatch(PromptSubmitted(cmd_id=cmd.cmd_id, user_text=text))
        self._cancel = asyncio.Event()
        self.run_worker(self._run_turn(cmd), group="turn", exclusive=True)

    async def _run_turn(self, cmd: SendPrompt) -> None:
        async for event in self.agent.run(cmd, self._cancel):
            self.store.dispatch(event)

    def set_llm(self, llm: Any) -> None:
        self.agent.llm = llm

    def action_cancel_or_quit(self) -> None:
        if self.app_state.is_processing:
            self._cancel.set()
        else:
            self.exit()
