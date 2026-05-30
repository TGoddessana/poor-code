# project_map/ — Disk Contract

Maps the on-disk artifact `<cwd>/.poor-code/project_map.json` to its
in-memory dataclass `ProjectMap` in `models.py`. The dataclass body is
the schema. Current schema: **`version: 2`** (a multi-language code graph;
V1 was a Python-only `ast` map).

## Files

| Disk path | Dataclass | Mutable on disk? | Created by |
|---|---|---|---|
| `project_map.json` | `ProjectMap` | yes — fully overwritten per session start | `ProjectMapStore.write` (called from `PoorCodeApp.on_mount` worker) |

The S1 placeholder `{"status": "uninitialized", "version": 1}` (written
by `SessionStore.ensure_project_map`) is overwritten on first successful
build.

## Schema v2 shape

`ProjectMap`: `version` (2), `generated_at`, `cwd`, `files[]`, `parse_errors[]`.

Per **file** (`FileEntry`):

- `path` — POSIX cwd-relative source path.
- `language` — detected language (`"python"`, `"javascript"`, `"typescript"`).
- `content_hash` — `"sha256:" + hexdigest` of the file bytes (drives incremental rebuilds).
- `symbols[]` — see below.
- `imports` — cwd-relative paths this file imports (internal only; externals dropped).
- `imported_by` — reverse edge: cwd-relative paths that import this file.
- `tests` — cwd-relative test files mapped to this source.

Per **symbol** (`Symbol`):

- `name` — qualified name (methods dotted, e.g. `Foo.bar`).
- `kind` — `SymbolKind` value (`class` / `function` / `method`).
- `lineno` — 1-based definition line.
- `signature` — parameter/return signature string for first-class languages; `null` when absent.
- `doc` — first docstring line for first-class languages; `null` when absent.
- `calls` — best-effort resolved call targets, each rendered `"<file>::<symbol>"`.
- `called_by` — reverse edge: `"<file>::<symbol>"` callers (sorted).

## Serialization conventions

- `datetime` → ISO 8601 string via `.isoformat()`. Always UTC.
- `Path` → absolute path string (used only for the top-level `cwd` field).
- `SymbolKind` → `.value` string. Unknown enum on read raises `ValueError`.
- All other `path` fields (file path, imports, imported_by, tests, parse_errors)
  are POSIX-style cwd-relative strings.
- `signature` / `doc` serialize as JSON `null` when absent and round-trip back to `None`.
- Tuples serialize as JSON arrays; lists in JSON deserialize to tuples.
- All writes are atomic (tmp file → `os.replace`). Partial writes never
  overwrite the original.

## Error policy

| Situation | Behavior |
|---|---|
| Per-file parse failure — tree-sitter ERROR-node tree, `OSError`, or unsupported language | Skip the file, append to `parse_errors[]`. Build continues. |
| Corrupt JSON or unknown enum on read | `ValueError("corrupt project map at ...")` |
| `version != 2` on read | Treated as stale; caller discards and rebuilds. |
| `os.replace` fails mid-write | Tmp file unlinked; original (or S1 placeholder) survives. |
| `cwd` not readable | `FileDiscovery` raises; UI emits `ProjectMapBuildFailed`. |

## Public surface

Downstream code (S3 onward) imports only from `poor_code.domain.project_map`:

```python
from poor_code.domain.project_map import ProjectMapBuilder, ProjectMap, FileEntry
```

Submodules (`discovery`, `languages`, `parsers` and its `extract`/`grammars`,
`import_resolver`, `call_resolver`, `tests_mapping`, internals of
`builder`/`store`) must not be imported by code outside this package.
