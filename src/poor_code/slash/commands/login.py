"""/login — opens a modal to configure a provider + API key + model.

On save: persists to auth_store, then swaps the running agent's LLM via
SlashContext.set_llm so the next turn uses the new credentials.
"""
from __future__ import annotations

from dataclasses import dataclass

from poor_code.infra import auth_store
from poor_code.provider.providers import ollama_cloud
from poor_code.slash.base import SlashContext
from poor_code.ui.screens.login import LoginResult, LoginScreen


def _build_llm(provider: str, *, model: str, api_key: str):
    if provider == "ollama_cloud":
        return ollama_cloud.client(model=model, api_key=api_key)
    raise ValueError(f"unknown provider: {provider}")


@dataclass
class LoginCommand:
    name: str = "login"
    description: str = "Configure an LLM provider"

    def execute(self, ctx: SlashContext, args: tuple[str, ...]) -> None:
        def on_done(result: LoginResult) -> None:
            if result is None:
                return
            provider, model, api_key = result
            auth_store.save(provider, api_key=api_key, model=model)
            ctx.set_llm(_build_llm(provider, model=model, api_key=api_key))
            ctx.notify(f"signed in: {provider} ({model})")

        ctx.push_screen(LoginScreen(), on_done)
