"""Parser dispatch by file extension. Internal — use only inside project_map."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from poor_code.domain.project_map.models import ParsedFile, ParseError
from poor_code.domain.project_map.parsers import python_ast


PARSERS: dict[str, Callable[[Path], ParsedFile]] = {".py": python_ast.parse}


def parse_file(path: Path) -> ParsedFile:
    parser = PARSERS.get(path.suffix)
    if parser is None:
        path_str = str(path)
        return ParsedFile(
            path=path_str,
            symbols=(),
            raw_imports=(),
            parse_error=ParseError(path=path_str, error="unsupported extension"),
        )
    return parser(path)
