"""Parser dispatch: path -> ParsedFile via tree-sitter. Internal.

Replaces the V1 ast parser. parse_file reads bytes, parses with the language's
grammar, flags trees containing ERROR nodes as parse errors, and delegates
structural extraction to extract.py.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from tree_sitter import Parser

from poor_code.domain.project_map import languages
from poor_code.domain.project_map.models import ParsedFile, ParseError
from poor_code.domain.project_map.parsers import extract, grammars


def parse_file(path: Path) -> ParsedFile:
    path_str = str(path)
    language = languages.detect_language(path)
    try:
        data = path.read_bytes()
    except OSError as e:
        return _err(path_str, "", f"{type(e).__name__}: {e}")
    content_hash = "sha256:" + hashlib.sha256(data).hexdigest()

    if language is None or not grammars.is_supported(language):
        return _err(path_str, language or "", "unsupported language", content_hash)

    try:
        lang = grammars.get_language(language)
        tree = Parser(lang).parse(data)
    except Exception as e:  # grammar/parse failure
        return _err(path_str, language, f"{type(e).__name__}: {e}", content_hash)

    root = tree.root_node
    if root.has_error:
        return _err(path_str, language, "SyntaxError: tree contains ERROR nodes", content_hash)

    first_class = languages.TIER.get(language) == "first"
    symbols, raw_imports, raw_calls = extract.extract(root, language, first_class)
    return ParsedFile(
        path=path_str, language=language, content_hash=content_hash,
        symbols=symbols, raw_imports=raw_imports, raw_calls=raw_calls, parse_error=None,
    )


def _err(path_str, language, msg, content_hash=""):
    return ParsedFile(
        path=path_str, language=language, content_hash=content_hash,
        symbols=(), raw_imports=(), raw_calls=(),
        parse_error=ParseError(path=path_str, error=msg),
    )
