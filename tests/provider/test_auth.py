import pytest

from poor_code.provider.auth import BearerAuth, MissingApiKey


def test_bearer_auth_apply_sets_authorization_header():
    auth = BearerAuth(token="sk-test")
    headers: dict[str, str] = {}
    auth.apply(headers)
    assert headers["Authorization"] == "Bearer sk-test"


def test_bearer_auth_from_env_reads_var(monkeypatch):
    monkeypatch.setenv("MY_KEY", "abc123")
    auth = BearerAuth.from_env("MY_KEY")
    assert auth.token == "abc123"


def test_bearer_auth_from_env_missing_raises(monkeypatch):
    monkeypatch.delenv("MY_KEY", raising=False)
    with pytest.raises(MissingApiKey, match="MY_KEY"):
        BearerAuth.from_env("MY_KEY")
