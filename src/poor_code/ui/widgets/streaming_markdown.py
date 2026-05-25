"""Markdown widget that supports incremental streaming via append + coalesce.

See textual.widgets.Markdown.append (added in Textual v4.0.0) and
textual.widgets._markdown.MarkdownStream for the underlying primitives."""
from __future__ import annotations

from textual.widgets import Markdown
from textual.widgets._markdown import MarkdownStream


def compute_delta(current: str, new: str) -> str | None:
    """Suffix to append so the widget's source becomes ``new``.

    Returns the tail to append, or ``None`` if ``new`` is not an extension
    of ``current`` (caller should fall back to a full replace)."""
    if not new.startswith(current):
        return None
    return new[len(current):]


class StreamingMarkdown(Markdown):
    """Markdown widget driven by an internal MarkdownStream.

    Callers pass the *full* accumulated text each time via ``write_delta``.
    The widget diffs against its own ``source`` and either streams the new
    tail through MarkdownStream (fast path) or falls back to a full
    ``update()`` when the text was rewritten (e.g. AssistantMessageCompleted
    normalizing the trailing segment)."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._stream: MarkdownStream | None = None

    def _ensure_stream(self) -> MarkdownStream:
        if self._stream is None:
            self._stream = Markdown.get_stream(self)
        return self._stream

    async def stop_stream(self) -> None:
        """Stop the stream and flush any pending writes."""
        if self._stream is not None:
            stream = self._stream
            self._stream = None
            await stream.stop()

    async def write_delta(self, new_text: str) -> None:
        """Make the widget's source equal ``new_text`` using append-streaming
        when possible, or a full update when the text was rewritten."""
        delta = compute_delta(self.source, new_text)
        if delta is None:
            await self.stop_stream()
            await self.update(new_text)
            return
        if not delta:
            return
        await self._ensure_stream().write(delta)

    def on_unmount(self) -> None:
        if self._stream is not None and self._stream._task is not None:
            self._stream._task.cancel()
            self._stream = None
