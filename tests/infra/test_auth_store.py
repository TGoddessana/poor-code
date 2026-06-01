import json
import stat

from poor_code.infra import auth_store


def _redirect_home(monkeypatch, tmp_path):
    monkeypatch.setattr(auth_store.Path, "home", classmethod(lambda cls: tmp_path))


def test_load_missing_returns_empty(monkeypatch, tmp_path):
    _redirect_home(monkeypatch, tmp_path)
    assert auth_store.load() == {"providers": {}}


def test_save_then_get_roundtrip(monkeypatch, tmp_path):
    _redirect_home(monkeypatch, tmp_path)
    auth_store.save("ollama_cloud", api_key="abc", model="m1")
    assert auth_store.get("ollama_cloud") == {"api_key": "abc", "model": "m1"}


def test_save_sets_0600_perms(monkeypatch, tmp_path):
    _redirect_home(monkeypatch, tmp_path)
    auth_store.save("ollama_cloud", api_key="abc", model="m1")
    p = tmp_path / ".poor-code" / "auth.json"
    mode = p.stat().st_mode & 0o777
    assert mode == stat.S_IRUSR | stat.S_IWUSR


def test_save_preserves_other_providers(monkeypatch, tmp_path):
    _redirect_home(monkeypatch, tmp_path)
    auth_store.save("ollama_cloud", api_key="a", model="m1")
    auth_store.save("other", api_key="b", model="m2")
    data = json.loads((tmp_path / ".poor-code" / "auth.json").read_text())
    assert set(data["providers"]) == {"ollama_cloud", "other"}


def test_load_corrupt_file_returns_empty(monkeypatch, tmp_path):
    _redirect_home(monkeypatch, tmp_path)
    p = tmp_path / ".poor-code" / "auth.json"
    p.parent.mkdir(parents=True)
    p.write_text("not json")
    assert auth_store.load() == {"providers": {}}
