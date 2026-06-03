"""/login — opens a modal to configure a provider + API key + model.

On save: persists to auth_store (which marks the provider active), then swaps
the running agent's LLM via SlashContext.set_llm so the next turn uses it.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from poor_code.infra import auth_store
from poor_code.provider.providers import build_llm
from poor_code.slash.base import Arg, ParsedArgs, SlashContext
from poor_code.ui.screens.login import LoginResult, LoginScreen


@dataclass
class LoginCommand:
    name: str = "login"
    description: str = "Configure an LLM provider"
    args: tuple[Arg, ...] = field(default_factory=tuple)

    def execute(self, ctx: SlashContext, parsed: ParsedArgs) -> None:
        def on_done(result: LoginResult) -> None:
            if result is None:
                return
            provider, model, api_key = result
            auth_store.save(provider, api_key=api_key, model=model)
            ctx.set_llm(build_llm(provider, model=model, api_key=api_key))
            ctx.notify(f"signed in: {provider} ({model})")

        ctx.push_screen(LoginScreen(), on_done)
