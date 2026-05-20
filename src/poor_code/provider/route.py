"""A Route is the (Protocol, Endpoint, Auth, Framing) tuple that fully
describes how to talk to one LLM HTTP endpoint. Providers (`providers/*.py`)
build Routes and hand them to `LLMClient`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from poor_code.provider.auth import Auth
from poor_code.provider.framing import Framing

if TYPE_CHECKING:
    from poor_code.provider.protocols.openai_chat import Protocol


@dataclass(frozen=True)
class Route:
    protocol: "Protocol"
    endpoint: str       # URL path, e.g. "/v1/chat/completions"
    auth: Auth
    framing: Framing
