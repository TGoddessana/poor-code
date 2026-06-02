"""Capabilities — what OpenAI request parameters one endpoint accepts.

Conservative defaults (all False) = send the safe minimum to unknown backends.
Each provider profile declares the features its endpoint actually honors."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Capabilities:
    response_format: bool = False      # accepts response_format json_schema
    tool_choice: bool = False          # accepts tool_choice
    parallel_tool_calls: bool = False  # accepts the parallel_tool_calls param
    strict_tools: bool = False         # accepts per-function strict
