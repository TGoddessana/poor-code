from textwrap import dedent

from textual.widgets import Static

from poor_code import __version__
from poor_code.ui.store import AppState


class Banner(Static):
    """Mascot banner — renders from app.app_state (cwd, provider_name, model)."""

    def on_mount(self) -> None:
        self.add_class("banner")
        self.watch(self.app, "app_state", self._on_state_change)
        self._apply_state(self.app.app_state)

    def _on_state_change(self, state: AppState) -> None:
        self._apply_state(state)

    def _apply_state(self, state: AppState) -> None:
        self.update(self._format(state))

    def render_plain(self) -> str:
        return self._format(self.app.app_state)

    @staticmethod
    def _format(state: AppState) -> str:
        if state.provider_name and state.model:
            status_line = f"provider: {state.provider_name} | model: {state.model}"
        else:
            status_line = "not configured — type /login"
        return dedent(
            f"""\
               (\\_/)   Poor-Code v{__version__}
               ( •_•)  cwd: {state.cwd}
               / >🥄  {status_line}"""
        )
