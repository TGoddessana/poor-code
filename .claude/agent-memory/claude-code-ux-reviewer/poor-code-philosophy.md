---
name: poor-code-philosophy
description: poor-code design philosophy — agent + tools as top-level primitives, 1급 추상화 목록
metadata:
  type: project
---

poor-code's philosophy: agent + tools are top-level primitives. The 9-layer pipeline is a research lens, not a folder structure.

First-class abstractions: Provider / Tool / SlashCommand / Hook / Profile

**Why:** This shapes how we evaluate UX — tool calls, agent state, and slash commands are not secondary features to bolt on. They must be first-class in the UI surface too.

**How to apply:** When reviewing UI, check that tool call visibility, agent state transparency, and slash command ergonomics are treated as primary surfaces, not footnotes. Don't overfit to the philosophy docs — critique the implementation.

[[user-role]]
