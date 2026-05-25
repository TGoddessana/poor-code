---
name: poor-code-stack
description: poor-code technical stack — Python 3.14 + Textual + uv. Benchmark: earendil-works/pi
metadata:
  type: project
---

Stack: Python 3.14 + Textual + uv

Benchmark for borrowing/differentiating: earendil-works/pi

Key architectural decisions observed:
- Redux-style immutable state store (AppState + reduce() + Store)
- Messages module is the UI/domain contract boundary (Commands in, Events out)
- Agent runs as a Textual worker (run_worker) with asyncio.Event for cancellation
- TurnAssembler builds transient API messages per-turn (POORCODE.md is never stored in history)
- Tool permission system: ToolContext.ask hook, currently stubbed as allow_all

Textual-specific constraints:
- No built-in spinner widget in older versions — must compose manually
- VerticalScroll scroll_end(animate=False) is the scroll-to-bottom pattern
- Widget refresh via remove_children() + re-compose is expensive; diff-aware update preferred
- CSS via .tcss files, reactive state via textual.reactive

[[poor-code-philosophy]]
