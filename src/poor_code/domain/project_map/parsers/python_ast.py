"""Python AST implementation of the parser contract.

Internal — exposed via parsers.parse_file dispatch.
"""
from __future__ import annotations

import ast
from pathlib import Path

from poor_code.domain.project_map.models import (
    ParsedFile,
    ParseError,
    RawImport,
    Symbol,
    SymbolKind,
)


def parse(path: Path) -> ParsedFile:
    path_str = str(path)
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return ParsedFile(
            path=path_str, symbols=(), raw_imports=(),
            parse_error=ParseError(path=path_str, error=f"{type(e).__name__}: {e}"),
        )
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return ParsedFile(
            path=path_str, symbols=(), raw_imports=(),
            parse_error=ParseError(path=path_str, error=f"SyntaxError: {e.msg} (line {e.lineno})"),
        )
    return ParsedFile(
        path=path_str,
        symbols=_extract_symbols(tree),
        raw_imports=_extract_imports(tree),
        parse_error=None,
    )


def _extract_symbols(tree: ast.Module) -> tuple[Symbol, ...]:
    out: list[Symbol] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            out.append(Symbol(name=node.name, kind=SymbolKind.CLASS, lineno=node.lineno))
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    out.append(
                        Symbol(
                            name=f"{node.name}.{sub.name}",
                            kind=SymbolKind.METHOD,
                            lineno=sub.lineno,
                        )
                    )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append(Symbol(name=node.name, kind=SymbolKind.FUNCTION, lineno=node.lineno))
    return tuple(out)


def _extract_imports(tree: ast.Module) -> tuple[RawImport, ...]:
    out: list[RawImport] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.append(RawImport(text=alias.name, level=0))
        elif isinstance(node, ast.ImportFrom):
            out.append(RawImport(text=node.module or "", level=node.level))
    return tuple(out)
