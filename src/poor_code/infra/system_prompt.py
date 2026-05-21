"""SystemPromptComposer — assembles the built-in system prompt and appends user files.

V1 always appends user files (global then project). The settings.json
`system_prompt_override` key is documented for future use but NOT consumed here.
"""
from __future__ import annotations

import platform
from dataclasses import dataclass
from pathlib import Path

from poor_code.infra.settings import Settings


DYNAMIC_BOUNDARY = "<!-- dynamic -->"

_STATIC = """You are poor-code, a TUI coding assistant that pairs a single LLM with a small set of local tools. You operate inside the user's project directory.

# Doing tasks
- The user primarily asks for software-engineering tasks: bug fixes, refactors, new features, explanations.
- Prefer editing existing files over creating new ones.
- Don't add comments unless the why is non-obvious.
- For UI/frontend changes, verify in a real browser before claiming done."""


@dataclass(frozen=True)
class SystemPrompt:
    text: str
    static: str
    dynamic: str


class SystemPromptComposer:
    def __init__(self, home_dir: Path | None = None) -> None:
        self._home = home_dir if home_dir is not None else Path.home()

    def compose(self, settings: Settings, cwd: Path) -> SystemPrompt:
        # `settings` is reserved for future fields (e.g. system_prompt_override);
        # V1 ignores it intentionally.
        del settings

        static = _STATIC
        dynamic = _build_dynamic(cwd)

        appendices: list[str] = []
        for path in (
            self._home / ".poor-code" / "system_prompt.md",
            cwd / ".poor-code" / "system_prompt.md",
        ):
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8")
            if text.strip():
                appendices.append(text.strip())

        parts = [static, DYNAMIC_BOUNDARY, dynamic, *appendices]
        return SystemPrompt(
            text="\n\n".join(parts),
            static=static,
            dynamic=dynamic,
        )


def _build_dynamic(cwd: Path) -> str:
    return (
        "# Environment\n"
        f"- Working directory: {cwd}\n"
        f"- Platform: {platform.system().lower()}"
    )
