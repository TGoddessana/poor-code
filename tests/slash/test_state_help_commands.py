from poor_code.slash.commands.state import StateCommand
from poor_code.slash.commands.help import HelpCommand
from poor_code.slash.base import ParsedArgs


class _Ctx:
    def __init__(self):
        self.pushed = None
        self.notified = None
    def push_screen(self, screen, callback=None):
        self.pushed = screen
    def notify(self, message, *, severity="information"):
        self.notified = message
    def set_llm(self, llm): ...


def test_state_command_pushes_inspector():
    from poor_code.ui.screens.state_inspector import StateInspector
    ctx = _Ctx()
    StateCommand().execute(ctx, ParsedArgs(values={}, raw=""))
    assert isinstance(ctx.pushed, StateInspector)


def test_help_command_notifies_keybindings():
    ctx = _Ctx()
    HelpCommand().execute(ctx, ParsedArgs(values={}, raw=""))
    assert ctx.notified and ("ctrl" in ctx.notified.lower() or "/" in ctx.notified)
