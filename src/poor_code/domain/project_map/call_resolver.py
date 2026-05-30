"""CallResolver — RawCall -> resolved internal call edges (best-effort). Internal.

Resolution: a call's bare callee resolves to (1) a symbol defined in the same file
whose last dotted segment matches, else (2) a project-wide unique match by last
segment, else it is dropped. Output keys are (file_path, qualified_symbol_name);
values are tuples of "file::symbol" targets. called_by is the reverse aggregation.
"""
from __future__ import annotations

from collections import defaultdict

from poor_code.domain.project_map.models import ParsedFile


def _bare(name: str) -> str:
    return name.split(".")[-1]


class CallResolver:
    def resolve(self, parsed_files: tuple[ParsedFile, ...]):
        # global index: bare name -> list of (file, qualified)
        global_index: dict[str, list[tuple[str, str]]] = defaultdict(list)
        per_file: dict[str, dict[str, str]] = {}
        for pf in parsed_files:
            local: dict[str, str] = {}
            for s in pf.symbols:
                b = _bare(s.name)
                local.setdefault(b, s.name)
                global_index[b].append((pf.path, s.name))
            per_file[pf.path] = local

        calls: dict[tuple[str, str], list[str]] = defaultdict(list)
        for pf in parsed_files:
            local = per_file[pf.path]
            for rc in pf.raw_calls:
                if not rc.caller:
                    continue  # module-level call; no owning symbol
                target = self._resolve_one(rc.callee, pf.path, local, global_index)
                if target is None:
                    continue
                key = (pf.path, rc.caller)
                if target not in calls[key]:
                    calls[key].append(target)

        calls_out = {k: tuple(v) for k, v in calls.items()}
        called_by: dict[tuple[str, str], list[str]] = defaultdict(list)
        for (src_file, src_sym), targets in calls_out.items():
            for t in targets:
                tf, _, ts = t.partition("::")
                called_by[(tf, ts)].append(f"{src_file}::{src_sym}")
        called_by_out = {k: tuple(sorted(v)) for k, v in called_by.items()}
        return calls_out, called_by_out

    @staticmethod
    def _resolve_one(callee, file_path, local, global_index):
        b = _bare(callee)
        if b in local:
            return f"{file_path}::{local[b]}"
        matches = global_index.get(b, [])
        if len(matches) == 1:
            f, qual = matches[0]
            return f"{f}::{qual}"
        return None
