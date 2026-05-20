lias claude-98='~/.local/share/claude/versions/2.1.98'
orCode Architecture Philosophy

## Core Premise

> Claude Code assumes the model is smart enough to figure it out.  
> PoorCode assumes the model is not — and builds structure to compensate.

The performance gap between small and large models in software engineering tasks
is primarily a **scaffolding gap**, not a capability gap.

---

## The Fundamental Difference

| | Claude Code (SOTA target) | PoorCode (small model target) |
|---|---|---|
| **Premise** | Model is capable | Model will fail without support |
| **Context** | Dump everything, model filters | Structure filters before model sees it |
| **File navigation** | Model decides what to read | Embedding-based Locator decides |
| **Planning** | Model plans on the fly | Orchestrator plans once, upfront |
| **Editing** | Model rewrites full files | Patch-only, smallest possible diff |
| **Failure** | Model retries with more context | Failure Memory provides structured hints |
| **Loop termination** | Model decides when done | Structure enforces step limits |

---

## Design Rule

Before adding any component, ask one question:

> **"Can this be done without an LLM?"**

If yes — do it without the LLM.  
The LLM is the bottleneck. Every token saved is a failure avoided.

---

## Layer Architecture

```
Issue
  ↓
[Issue Normalizer]      — rule-based. classify, extract keywords. no LLM.
  ↓
[Repo Indexer]          — embed codebase once. nomic-embed-code. no LLM.
  ↓
[Locator]               — semantic vector search. find relevant files/functions. no LLM.
  ↓
[Impact Analyzer]       — static import graph. find what breaks if X changes. no LLM.
  ↓
[Orchestrator]          — LLM call #1. thinking mode ON. produce TODO list only.
  ↓
[Editor]                — LLM call per TODO item. thinking mode OFF. patch only.
  ↓
[Validator]             — AST check → run tests → LLM as last resort.
  ↓
Patch
  ↑
[Failure Memory]        — rule-based. log failure patterns. inject as hints on retry.
[Context Manager]       — rule-based. filter context per layer. each layer sees only what it needs.
```

---

## Layer-by-Layer Rationale

### Issue Normalizer — no LLM
Classify the issue type (bug / feature / refactor), extract keywords, detect affected module names.
A small model given a raw GitHub issue will hallucinate file paths that don't exist.
Rule-based extraction is deterministic and costs zero tokens.

### Repo Indexer — no LLM
Embed the entire codebase once at session start using `nomic-embed-code`.
Store in ChromaDB. Reuse across all issues in the session.
A small model cannot hold a full repository in context. The index replaces that need.

### Locator — no LLM
Given the normalized issue keywords, run semantic search over the embedded codebase.
Return the top-K most relevant files and functions.
This is the single most important layer for small models.
Without it, the model sees too much and loses focus. With it, the model sees exactly what matters.

### Impact Analyzer — no LLM
Parse the import graph of located files.
Flag any files that import the located files — they may need updating too.
Small models do not reliably trace cross-file dependencies. Static analysis does.

### Orchestrator — LLM, thinking ON, called once
Given: issue summary + located files + impact map.
Output: a numbered TODO list. nothing else.
Thinking mode ON because planning requires reasoning.
Called exactly once. The plan does not change mid-execution.
If the plan is wrong, the session fails cleanly — not after 20 wasted steps.

### Editor — LLM, thinking OFF, called per TODO item
Given: one TODO item + the single file it affects + the current file content.
Output: a search-and-replace patch. nothing else.
Thinking mode OFF because execution does not require reasoning — it requires precision.
Context is strictly limited to the current TODO item. No history. No other files.
This is the sequential context pattern: many small calls instead of one large call.

### Validator — AST first, LLM last
Three-stage validation in order:
1. AST parse the patched file. If syntax error, reject immediately.
2. Run the relevant test suite. If tests pass, done.
3. Only if tests fail AND we have retries left: ask LLM to diagnose.
The LLM is the most expensive validator. It is used last.

### Failure Memory — no LLM
When a patch fails, record: which file, which TODO item, what error, what was tried.
On retry, inject this as a structured hint into the Editor context.
Small models repeat the same mistakes without memory. This breaks the loop.

### Context Manager — no LLM
Each layer receives only the context relevant to its task.
The Editor does not see the full TODO list — only the current item.
The Orchestrator does not see file contents — only summaries.
Context isolation prevents small models from being distracted by irrelevant information.

---

## What This Architecture Does Not Do

These are explicit non-goals, not oversights:

- **Does not give the model the full repository.** Ever.
- **Does not let the model decide which files to read.** The Locator does.
- **Does not let the model plan and execute in the same call.** Orchestrator and Editor are separate.
- **Does not retry by adding more context.** Failure Memory adds structured hints, not raw history.
- **Does not assume the model follows JSON tool call format perfectly.** Validator catches malformed output early.

---

## The Sequential Context Pattern

Instead of one long context window:

```
❌ Single call:  [50K token context] → model tries to solve everything
✅ Sequential:   [2K context] → step 1 done → [2K context] → step 2 done → ...
```

Each call passes a structured handoff memo to the next:

```
"Completed: updated _cstack() signature in separable.py.
 Next: update all callers of _cstack() in the same file."
```

The model never needs to remember what happened three steps ago.
The structure remembers. The model only needs to execute the current step.

---

## Cost Model

PoorCode is cheap not because it makes fewer calls,
but because each call has a small context.

```
Typical SOTA agent:   1 call  × 50,000 tokens = 50,000 tokens total
PoorCode:             6 calls ×  2,000 tokens = 12,000 tokens total
```

At zero-marginal-cost (local inference), this distinction disappears.
But it matters for the quality of each call: smaller context = more focused model = fewer hallucinations.

---

## Summary

```
SOTA agents:    strong model  →  simple harness
PoorCode:       weak model    →  structure does the thinking
```

Every layer that replaces LLM reasoning with deterministic computation
is a layer that cannot hallucinate, cannot lose context, and cannot fail unpredictably.

The goal is not to make the small model smarter.
The goal is to make the problem small enough that the small model can solve it.

