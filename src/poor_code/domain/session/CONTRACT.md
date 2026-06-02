# session/ — Disk Contract

Maps each on-disk JSON file under `<cwd>/.poor-code/` to its in-memory dataclass.
The dataclass body in `models.py` is the schema. Disk JSON is its serialization.

## Files

| Disk path | Dataclass | Mutable on disk? | Created by |
|---|---|---|---|
| `project_map.json` | (not a session dataclass — see S2) | yes | `SessionService.start_session` writes placeholder if missing |
| `sessions/<sid>/session.json` | `Session` | no | `SessionService.start_session` |
| `sessions/<sid>/state.json` | `SessionState` | yes | `SessionService.start_session`, updated by `begin_task` / `end_task` |
| `sessions/<sid>/tasks/<tid>/request.json` | `WorkItem` | no | `SessionService.begin_task` |
| `sessions/<sid>/tasks/<tid>/state.json` | `WorkItemState` | yes | `SessionService.begin_task`, updated by `end_task` |

## Serialization conventions

- `datetime` → ISO 8601 string via `.isoformat()`. Always timezone-aware (UTC).
- `Path` → absolute path string.
- `Enum` → `.value` string. Unknown enum on read raises `ValueError`.
- All writes are atomic (tmp file → `os.replace`). Partial writes never overwrite the original.

## Public surface

Downstream code (S2~S9) imports only from `poor_code.domain.session`:

```python
from poor_code.domain.session import SessionService, WorkItem, WorkItemStatus  # etc.
```

`store`, `paths` are package-internal. Path resolution outside the package goes through
`SessionService.task_dir(task_id)`. Filenames within `task_dir` are owned by the
sub-project that writes them (e.g. S4 owns `requirement_artifact.json`).

## Placeholder discipline

`SessionService.begin_task` writes only `request.json` and `state.json` under
`tasks/<tid>/`. Sibling artifacts (`requirement_artifact.json`, `tasks.json`,
`attempts/`, `failure_memory.jsonl`, `final_report.md`) are NOT pre-created.
The sub-project that owns each artifact mkdir/touches it the first time it writes.
