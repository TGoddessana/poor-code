from __future__ import annotations

import asyncio

from textual.app import App, ComposeResult

from poor_code.ui.widgets.streaming_markdown import (
    StreamingMarkdown,
    compute_delta,
)


def test_compute_delta_prefix_match_returns_tail():
    assert compute_delta(current="Hello", new="Hello world") == " world"


def test_compute_delta_empty_current_returns_full():
    assert compute_delta(current="", new="Hello") == "Hello"


def test_compute_delta_identical_returns_empty():
    assert compute_delta(current="abc", new="abc") == ""


def test_compute_delta_non_prefix_returns_none():
    # AssistantMessageCompleted may rewrite the trailing segment with a
    # normalized final text. Signal "full replace" by returning None.
    assert compute_delta(current="Hello wrld", new="Hello world") is None


class _Host(App):
    def compose(self) -> ComposeResult:
        yield StreamingMarkdown(id="md")


async def test_write_delta_appends_incrementally():
    async with _Host().run_test() as pilot:
        md = pilot.app.query_one(StreamingMarkdown)
        await pilot.pause()
        await md.write_delta("Hello")
        await pilot.pause()
        await md.write_delta("Hello world")
        await pilot.pause()
        # MarkdownStream may coalesce — flush by stopping the stream.
        await md.stop_stream()
        await pilot.pause()
        assert md.source == "Hello world"


async def test_write_delta_falls_back_on_non_prefix():
    async with _Host().run_test() as pilot:
        md = pilot.app.query_one(StreamingMarkdown)
        await pilot.pause()
        await md.write_delta("Hello wrld")
        await md.stop_stream()
        await pilot.pause()
        await md.write_delta("Hello world")  # not a prefix extension
        await pilot.pause()
        assert md.source == "Hello world"


async def test_unmount_cancels_stream():
    async with _Host().run_test() as pilot:
        md = pilot.app.query_one(StreamingMarkdown)
        await pilot.pause()
        await md.write_delta("Hello")
        await pilot.pause()
        stream_task = md._stream._task if md._stream is not None else None
        assert stream_task is not None
        await md.remove()
        await pilot.pause()
        await asyncio.sleep(0)
        assert stream_task.done()
