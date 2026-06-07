"""StepNarrator — the seam for turning a graph step into human narration.

domain defines only the Protocol; concrete implementations live where they can
read presentation language (ui/) or come from a future LLM driver. The Driver
never constructs one — it passes raw (node, phase, state) / (node, result) to
the sink, which holds an injected narrator. This keeps domain language-agnostic
and lets an LLM driver supply narration without any UI change."""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class StepNarrator(Protocol):
    def activity(self, node: str, phase, state) -> str:
        """Present-tense sentence for entering `node`."""
        ...

    def summary(self, node: str, result) -> tuple[str, tuple[str, ...]]:
        """(headline, detail) describing what `node` produced. ('', ()) → no card."""
        ...
