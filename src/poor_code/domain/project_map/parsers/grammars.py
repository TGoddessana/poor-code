"""Registry: language name -> (tree_sitter.Language, tags.scm text). Internal.

Each grammar package ships queries/tags.scm; we read it from the package dir.
If a future language's package omits tags.scm, drop a copy under parsers/queries/
named "<language>-tags.scm" and it will be preferred.
"""
from __future__ import annotations

import os
from functools import lru_cache

import tree_sitter_javascript
import tree_sitter_python
import tree_sitter_typescript
from tree_sitter import Language

_VENDOR_DIR = os.path.join(os.path.dirname(__file__), "queries")

# language -> (callable returning the raw TSLanguage pointer, grammar module)
_GRAMMARS = {
    "python": (tree_sitter_python.language, tree_sitter_python),
    "javascript": (tree_sitter_javascript.language, tree_sitter_javascript),
    "typescript": (tree_sitter_typescript.language_typescript, tree_sitter_typescript),
}


@lru_cache(maxsize=None)
def get_language(language: str) -> Language:
    factory, _mod = _GRAMMARS[language]
    return Language(factory())


@lru_cache(maxsize=None)
def get_tags_query(language: str) -> str:
    # Prefer a vendored override.
    vendored = os.path.join(_VENDOR_DIR, f"{language}-tags.scm")
    if os.path.isfile(vendored):
        with open(vendored, encoding="utf-8") as fh:
            return fh.read()
    _factory, mod = _GRAMMARS[language]
    bundled = os.path.join(os.path.dirname(mod.__file__), "queries", "tags.scm")
    with open(bundled, encoding="utf-8") as fh:
        return fh.read()


def is_supported(language: str) -> bool:
    return language in _GRAMMARS
