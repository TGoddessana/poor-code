from poor_code.provider.client import LLMClient
from poor_code.slash.base import ParsedArgs
from poor_code.slash.commands.login import LoginCommand


class _FakeCtx:
    """Minimal SlashContext stand-in: captures the on_done callback and effects."""
    def __init__(self):
        self.pushed_on_done = None
        self.llm = None
        self.notices = []

    def push_screen(self, screen, on_done):
        self.pushed_on_done = on_done

    def set_llm(self, llm):
        self.llm = llm

    def notify(self, msg):
        self.notices.append(msg)


def test_login_on_done_builds_llm_and_saves(monkeypatch):
    saved = {}
    monkeypatch.setattr(
        "poor_code.slash.commands.login.auth_store.save",
        lambda provider, *, api_key, model: saved.update(
            provider=provider, api_key=api_key, model=model),
    )
    ctx = _FakeCtx()
    LoginCommand().execute(ctx, ParsedArgs(values={}, raw=""))
    assert ctx.pushed_on_done is not None

    # Simulate the modal returning resolved (non-blank) credentials.
    ctx.pushed_on_done(("openai", "gpt-5.4-mini", "sk-xyz"))

    assert saved == {"provider": "openai", "model": "gpt-5.4-mini", "api_key": "sk-xyz"}
    assert isinstance(ctx.llm, LLMClient)
    assert ctx.llm.base_url == "https://api.openai.com"
    assert any("openai" in n for n in ctx.notices)


def test_login_on_done_noop_on_cancel(monkeypatch):
    monkeypatch.setattr(
        "poor_code.slash.commands.login.auth_store.save",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not save")),
    )
    ctx = _FakeCtx()
    LoginCommand().execute(ctx, ParsedArgs(values={}, raw=""))
    ctx.pushed_on_done(None)  # cancel
    assert ctx.llm is None
