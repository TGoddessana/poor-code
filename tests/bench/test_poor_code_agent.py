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


def test_env_passthrough(monkeypatch):
    monkeypatch.setenv("OLLAMA_API_KEY", "key-123")
    monkeypatch.setenv("POOR_CODE_MODEL", "model-x")
    mod = _load_agent_module()
    env = mod.build_env()
    assert env["OLLAMA_API_KEY"] == "key-123"
    assert env["POOR_CODE_MODEL"] == "model-x"


def test_env_requires_both(monkeypatch):
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    monkeypatch.setenv("POOR_CODE_MODEL", "m")
    mod = _load_agent_module()
    with pytest.raises(KeyError):
        mod.build_env()


def test_install_script_exists_and_is_shell():
    text = (REPO / "bench" / "install.sh").read_text()
    assert text.startswith("#!/")
    assert "poor-code" in text or "poor_code" in text
