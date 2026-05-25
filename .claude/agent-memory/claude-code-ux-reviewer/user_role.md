---
name: user-role
description: User is a backend developer building poor-code (Python TUI, Claude Code clone). Frame UI/frontend feedback in backend analogies.
metadata:
  type: user
---

User is a backend developer. When discussing UI/frontend concerns, explain in backend analogies:
- Modals = blocking RPC calls
- State transitions = database transactions
- Streaming = chunked HTTP responses
- Tool call visibility = distributed trace spans
- Spinner/loading states = async task status polling
- Keyboard focus = lock acquisition

They are building poor-code as a Claude Code clone using Python 3.14 + Textual + uv.
They care deeply about full-time developer experience — friction compounds over a workday.

[[poor-code-philosophy]]
[[poor-code-stack]]
