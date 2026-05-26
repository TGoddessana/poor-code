# project_map/ — Disk Contract

Maps the on-disk artifact `<cwd>/.poor-code/project_map.json` to its
in-memory dataclass `ProjectMap` in `models.py`. The dataclass body is
the schema.

## Files

| Disk path | Dataclass | Mutable on disk? | Created by |
|---|---|---|---|
| `project_map.json` | `ProjectMap` | yes — fully overwritten per session start | `ProjectMapStore.write` (called from `PoorCodeApp.on_mount` worker) |

The S1 placeholder `{"status": "uninitialized", "version": 1}` (written
by `SessionStore.ensure_project_map`) is overwritten on first successful
build. The two schemas share `version: 1` only by coincidence.

## Serialization conventions

- `datetime` → ISO 8601 string via `.isoformat()`. Always UTC.
- `Path` → absolute path string (used only for the top-level `cwd` field).
- `SymbolKind` → `.value` string. Unknown enum on read raises `ValueError`.
- All other `path` fields (file path, imports, tests, parse_errors) are
  POSIX-style cwd-relative strings.
- Tuples serialize as JSON arrays; lists in JSON deserialize to tuples.
- All writes are atomic (tmp file → `os.replace`). Partial writes never
  overwrite the original.

## Error policy

| Situation | Behavior |
|---|---|
| Per-file `SyntaxError` / `OSError` / `UnicodeDecodeError` | Skip the file, append to `parse_errors[]`. Build continues. |
| Corrupt JSON or unknown enum on read | `ValueError("corrupt project map at ...")` |
| `os.replace` fails mid-write | Tmp file unlinked; original (or S1 placeholder) survives. |
| `cwd` not readable | `FileDiscovery` raises; UI emits `ProjectMapBuildFailed`. |

## Public surface

Downstream code (S3 onward) imports only from `poor_code.domain.project_map`:

```python
from poor_code.domain.project_map import ProjectMapBuilder, ProjectMap, FileEntry
```

Submodules (`discovery`, `parsers`, `import_resolver`, `tests_mapping`,
`paths`, internals of `builder`/`store`) must not be imported by code
outside this package.
