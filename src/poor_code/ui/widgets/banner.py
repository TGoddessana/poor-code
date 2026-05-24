from textwrap import dedent

from rich.table import Table
from textual.widgets import Static

from poor_code import __version__
from poor_code.ui.store import AppState

MASCOT = dedent("""\
    (\\_/)
    ( •_•)
    / >🥄""")


class Banner(Static):
    """Mascot banner — renders from app.app_state (cwd, provider_name, model)."""

    def on_mount(self) -> None:
        self.add_class("banner")
        self.watch(self.app, "app_state", self._on_state_change)
        self._apply_state(self.app.app_state)

    def _on_state_change(self, state: AppState) -> None:
        self._apply_state(state)

    def _apply_state(self, state: AppState) -> None:
        self.update(self._build_renderable(state))

    def render_plain(self) -> str:
        return self._format_plain(self.app.app_state)

    @staticmethod
    def _status_line(state: AppState) -> str:
        if state.provider_name and state.model:
            return f"provider: {state.provider_name} | model: {state.model}"
        return "not configured — type /login"

    @classmethod
    def _info(cls, state: AppState) -> str:
        return (
            f"Poor-Code v{__version__}\n"
            f"cwd: {state.cwd}\n"
            f"{cls._status_line(state)}"
        )

    @classmethod
    def _build_renderable(cls, state: AppState) -> Table:
        table = Table.grid(padding=(0, 2))
        table.add_column(no_wrap=True)
        table.add_column()
        table.add_row(MASCOT, cls._info(state))
        return table

    @classmethod
    def _format_plain(cls, state: AppState) -> str:
        return f"{MASCOT}\n{cls._info(state)}"
