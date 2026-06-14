import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _load_agent_module():
    spec = importlib.util.spec_from_file_location(
        "poor_code_agent", REPO / "bench" / "poor_code_agent.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_run_command_quotes_instruction(monkeypatch):
    monkeypatch.setenv("OLLAMA_API_KEY", "k")
    monkeypatch.setenv("POOR_CODE_MODEL", "m")
    mod = _load_agent_module()
    cmds = mod.build_run_commands("fix the bug; rm -rf /")
    assert len(cmds) == 1
    # instruction is shell-quoted into a single --headless arg
    assert "--headless" in cmds[0]
    assert "'fix the bug; rm -rf /'" in cmds[0]


def _clear_keys(monkeypatch):
    for k in ("OLLAMA_API_KEY", "OPENAI_API_KEY", "POOR_CODE_API_KEY",
              "POOR_CODE_PROVIDER"):
        monkeypatch.delenv(k, raising=False)


def test_env_passthrough_ollama(monkeypatch):
    _clear_keys(monkeypatch)
    monkeypatch.setenv("OLLAMA_API_KEY", "key-123")
    monkeypatch.setenv("POOR_CODE_MODEL", "model-x")
    mod = _load_agent_module()
    env = mod.build_env()
    assert env["OLLAMA_API_KEY"] == "key-123"
    assert env["POOR_CODE_MODEL"] == "model-x"


def test_env_passthrough_openai(monkeypatch):
    _clear_keys(monkeypatch)
    monkeypatch.setenv("POOR_CODE_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-1")
    monkeypatch.setenv("POOR_CODE_MODEL", "gpt-5.4-mini")
    mod = _load_agent_module()
    env = mod.build_env()
    assert env["POOR_CODE_PROVIDER"] == "openai"
    assert env["OPENAI_API_KEY"] == "sk-1"
    assert env["POOR_CODE_MODEL"] == "gpt-5.4-mini"
    assert "OLLAMA_API_KEY" not in env


def test_env_forwards_git_ref_and_url_when_set(monkeypatch):
    _clear_keys(monkeypatch)
    monkeypatch.setenv("OLLAMA_API_KEY", "k")
    monkeypatch.setenv("POOR_CODE_MODEL", "m")
    monkeypatch.setenv("POOR_CODE_GIT_REF", "feat/x")
    monkeypatch.setenv("POOR_CODE_GIT_URL", "https://example.com/repo")
    mod = _load_agent_module()
    env = mod.build_env()
    assert env["POOR_CODE_GIT_REF"] == "feat/x"
    assert env["POOR_CODE_GIT_URL"] == "https://example.com/repo"


def test_env_forwards_dump_prompts_when_set(monkeypatch):
    # The verifier diagnostic: a /logs container path is forwarded so the prompt+verdict
    # dump lands in the run artifacts. Forwarded verbatim, only when the host sets it.
    _clear_keys(monkeypatch)
    monkeypatch.setenv("OLLAMA_API_KEY", "k")
    monkeypatch.setenv("POOR_CODE_MODEL", "m")
    monkeypatch.setenv("POOR_CODE_DUMP_PROMPTS", "/logs/poorcode-dump.txt")
    mod = _load_agent_module()
    assert mod.build_env()["POOR_CODE_DUMP_PROMPTS"] == "/logs/poorcode-dump.txt"


def test_env_omits_dump_prompts_when_unset(monkeypatch):
    _clear_keys(monkeypatch)
    monkeypatch.delenv("POOR_CODE_DUMP_PROMPTS", raising=False)
    monkeypatch.setenv("OLLAMA_API_KEY", "k")
    monkeypatch.setenv("POOR_CODE_MODEL", "m")
    mod = _load_agent_module()
    assert "POOR_CODE_DUMP_PROMPTS" not in mod.build_env()


def test_env_omits_git_ref_when_unset(monkeypatch):
    _clear_keys(monkeypatch)
    monkeypatch.delenv("POOR_CODE_GIT_REF", raising=False)
    monkeypatch.setenv("OLLAMA_API_KEY", "k")
    monkeypatch.setenv("POOR_CODE_MODEL", "m")
    mod = _load_agent_module()
    assert "POOR_CODE_GIT_REF" not in mod.build_env()


def test_env_requires_model(monkeypatch):
    _clear_keys(monkeypatch)
    monkeypatch.delenv("POOR_CODE_MODEL", raising=False)
    monkeypatch.setenv("OLLAMA_API_KEY", "k")
    mod = _load_agent_module()
    with pytest.raises(KeyError):
        mod.build_env()


def test_env_requires_a_credential(monkeypatch):
    _clear_keys(monkeypatch)
    monkeypatch.setenv("POOR_CODE_MODEL", "m")
    mod = _load_agent_module()
    with pytest.raises(KeyError):
        mod.build_env()


def test_install_script_exists_and_is_shell():
    text = (REPO / "bench" / "install.sh").read_text()
    assert text.startswith("#!/")
    assert "poor-code" in text or "poor_code" in text
