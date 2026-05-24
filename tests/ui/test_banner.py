from textual.app import App, ComposeResult
from textual.reactive import reactive

from poor_code.ui.store import AppState, ProviderChanged, Store
from poor_code.ui.widgets.banner import Banner


class _Harness(App):
    """Minimal host so Banner can read app.app_state."""

    app_state: reactive[AppState] = reactive(AppState(), layout=False)

    def __init__(self, store: Store) -> None:
        super().__init__()
        self.store = store

    def on_mount(self) -> None:
        self.store.subscribe(lambda s: setattr(self, "app_state", s))
        self.app_state = self.store.state

    def compose(self) -> ComposeResult:
        yield Banner()


async def test_banner_shows_not_configured_when_provider_missing():
    store = Store(AppState(cwd="/home/dev"))
    async with _Harness(store).run_test() as pilot:
        await pilot.pause()
        banner = pilot.app.query_one(Banner)
        text = banner.render_plain()
        assert "cwd: /home/dev" in text
        assert "not configured" in text
        assert "/login" in text


async def test_banner_shows_provider_and_model_when_set():
    store = Store(AppState(cwd="/x"))
    async with _Harness(store).run_test() as pilot:
        await pilot.pause()
        store.dispatch(ProviderChanged(provider_name="ollama cloud", model="gpt-oss:120b"))
        await pilot.pause()
        banner = pilot.app.query_one(Banner)
        text = banner.render_plain()
        assert "provider: ollama cloud" in text
        assert "model: gpt-oss:120b" in text


async def test_banner_updates_when_provider_changes_mid_session():
    store = Store(AppState(cwd="/x", provider_name="ollama cloud", model="m1"))
    async with _Harness(store).run_test() as pilot:
        await pilot.pause()
        store.dispatch(ProviderChanged(provider_name="ollama cloud", model="m2"))
        await pilot.pause()
        text = pilot.app.query_one(Banner).render_plain()
        assert "model: m2" in text
        assert "model: m1" not in text
