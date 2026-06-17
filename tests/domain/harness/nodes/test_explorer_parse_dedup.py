"""Explorer.parse de-duplicates repeated CodeRefs. Weak models re-emit the same
(file, symbol) candidate several times; the parsed CodeContext must collapse them
so one file does not flood candidates with identical refs."""
import json
from datetime import UTC, datetime
from pathlib import Path

from poor_code.domain.harness.nodes.explorer import ExploringNode
from poor_code.domain.project_map.models import ProjectMap
from poor_code.domain.tool.registry import ToolRegistry
from poor_code.domain.tool.read import ReadTool


class _NoLLM:
    async def stream(self, messages, tools, response_format=None):
        if False:
            yield None


def _node():
    pm = ProjectMap(version=2, generated_at=datetime.now(UTC), cwd=Path("."),
                    files=(), parse_errors=())
    return ExploringNode(_NoLLM(), project_map=pm, tools=ToolRegistry([ReadTool()]))


def test_parse_dedups_repeated_candidate_refs():
    args = json.dumps({
        "candidates": [
            {"file": "prompt_box.py", "symbol": "PromptBox"},
            {"file": "prompt_box.py", "symbol": "PromptBox"},   # exact dup
            {"file": "prompt_box.py", "symbol": "PromptBox"},   # exact dup
            {"file": "prompt_box.py", "symbol": "compose"},     # distinct symbol → kept
            {"file": "prompt_box.py"},                          # file-only → kept (symbol=None)
        ],
        "confusers": [],
        "related_tests": [
            {"file": "t.py"}, {"file": "t.py"},                 # dup test ref
        ],
        "grounding": "not_found",
    })
    cc = _node().parse(args)
    cands = [(r.file, r.symbol) for r in cc.candidates]
    assert cands == [
        ("prompt_box.py", "PromptBox"),
        ("prompt_box.py", "compose"),
        ("prompt_box.py", None),
    ]
    assert len(cc.related_tests) == 1
