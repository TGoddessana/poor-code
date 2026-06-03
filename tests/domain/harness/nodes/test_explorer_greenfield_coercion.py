"""An empty working tree (no files in the project map) with no candidates is
unambiguously greenfield. The model kept guessing 'not_found' for an empty /app,
which made the UnderstandingGate bounce then escalate -> ABANDONED before the
planner ever ran. parse() must coerce that case to GREENFIELD deterministically."""
import json
from datetime import UTC, datetime
from pathlib import Path

from poor_code.domain.harness.nodes.explorer import ExploringNode
from poor_code.domain.project_map.models import (
    FileEntry, ProjectMap, Symbol, SymbolKind,
)
from poor_code.domain.session.models import GroundingStatus


def _empty_map():
    return ProjectMap(version=2, generated_at=datetime.now(UTC), cwd=Path("."),
                      files=(), parse_errors=())


def _nonempty_map():
    sym = Symbol(name="login", kind=SymbolKind.FUNCTION, lineno=1,
                 signature=None, doc=None, calls=(), called_by=())
    fe = FileEntry(path="a.py", language="python", content_hash="h",
                   symbols=(sym,), imports=(), imported_by=(), tests=())
    return ProjectMap(version=2, generated_at=datetime.now(UTC), cwd=Path("."),
                      files=(fe,), parse_errors=())


def _node(pm):
    return ExploringNode(llm=None, project_map=pm, tools=None)


_NOT_FOUND_EMPTY = json.dumps(
    {"candidates": [], "confusers": [], "related_tests": [],
     "search_notes": "nothing here", "grounding": "not_found", "summary": "empty"})


def test_empty_tree_with_no_candidates_is_coerced_to_greenfield():
    cc = _node(_empty_map()).parse(_NOT_FOUND_EMPTY)
    assert cc.grounding is GroundingStatus.GREENFIELD


def test_nonempty_tree_not_found_stays_not_found():
    # In a repo that DOES have code, an empty result is a genuine "couldn't find",
    # not greenfield — don't mask it.
    cc = _node(_nonempty_map()).parse(_NOT_FOUND_EMPTY)
    assert cc.grounding is GroundingStatus.NOT_FOUND


def test_model_greenfield_is_respected_on_empty_tree():
    payload = json.dumps(
        {"candidates": [], "confusers": [], "related_tests": [],
         "search_notes": "", "grounding": "greenfield", "summary": "build from scratch"})
    cc = _node(_empty_map()).parse(payload)
    assert cc.grounding is GroundingStatus.GREENFIELD
