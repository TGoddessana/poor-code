"""Extraction from a tree-sitter tree into our model. Internal.

Two passes over the tree, both via field-navigation (no captures needed for the
structural part — tags.scm captures don't give method-vs-function or dotted names):
  - symbols: walk class/function definitions, dotting methods, reading signature+doc
  - raw_calls: walk call sites, attributing each to its enclosing definition
Imports use language-specific node types.
"""
from __future__ import annotations

from poor_code.domain.project_map.models import (
    RawCall, RawImport, Symbol, SymbolKind,
)

_MAX_AST_DEPTH = 180

# Per-language node-type config (first-class langs).
_CFG = {
    "python": {
        "class": {"class_definition"},
        "func": {"function_definition"},
        "call": {"call"},
        "call_fn_field": "function",
        "import": {"import_statement", "import_from_statement"},
    },
    "javascript": {
        "class": {"class_declaration"},
        "func": {"function_declaration", "method_definition"},
        "call": {"call_expression"},
        "call_fn_field": "function",
        "import": {"import_statement"},
    },
    "typescript": {
        "class": {"class_declaration"},
        "func": {"function_declaration", "method_definition"},
        "call": {"call_expression"},
        "call_fn_field": "function",
        "import": {"import_statement"},
    },
}


def extract(root, language: str, first_class: bool):
    cfg = _CFG[language]
    symbols: list[Symbol] = []
    _collect_symbols(root, cfg, first_class, prefix=None, depth=0, out=symbols)
    raw_calls = tuple(_collect_calls(root, cfg, depth=0, enclosing=""))
    raw_imports = tuple(_collect_imports(root, cfg, language))
    return tuple(symbols), raw_imports, raw_calls


def _name_of(node) -> str | None:
    n = node.child_by_field_name("name")
    return n.text.decode("utf-8", "replace") if n is not None else None


def _collect_symbols(node, cfg, first_class, prefix, depth, out):
    if depth > _MAX_AST_DEPTH:
        return
    for child in node.named_children:
        if child.type in cfg["class"]:
            name = _name_of(child)
            if name is None:
                continue
            qual = f"{prefix}.{name}" if prefix else name
            out.append(Symbol(name=qual, kind=SymbolKind.CLASS, lineno=child.start_point[0] + 1,
                              signature=None, doc=_docstring(child) if first_class else None,
                              calls=(), called_by=()))
            body = child.child_by_field_name("body")
            if body is not None:
                # methods are functions directly inside a class body
                for m in body.named_children:
                    if m.type in cfg["func"]:
                        mname = _name_of(m)
                        if mname is None:
                            continue
                        out.append(Symbol(name=f"{qual}.{mname}", kind=SymbolKind.METHOD,
                                          lineno=m.start_point[0] + 1,
                                          signature=_signature(m) if first_class else None,
                                          doc=_docstring(m) if first_class else None,
                                          calls=(), called_by=()))
        elif child.type in cfg["func"]:
            name = _name_of(child)
            if name is None:
                continue
            qual = f"{prefix}.{name}" if prefix else name
            out.append(Symbol(name=qual, kind=SymbolKind.FUNCTION, lineno=child.start_point[0] + 1,
                              signature=_signature(child) if first_class else None,
                              doc=_docstring(child) if first_class else None,
                              calls=(), called_by=()))
        else:
            # descend into other containers (e.g. module, decorated_definition)
            _collect_symbols(child, cfg, first_class, prefix, depth + 1, out)


def _signature(fn) -> str | None:
    params = fn.child_by_field_name("parameters")
    ret = fn.child_by_field_name("return_type")
    sig = params.text.decode("utf-8", "replace") if params is not None else "()"
    if ret is not None:
        sig += " -> " + ret.text.decode("utf-8", "replace")
    return sig


def _docstring(node) -> str | None:
    body = node.child_by_field_name("body")
    if body is None or not body.named_children:
        return None
    first = body.named_children[0]
    if first.type == "expression_statement" and first.named_children:
        s = first.named_children[0]
        if s.type in ("string",):
            raw = s.text.decode("utf-8", "replace").strip().strip('"\'')
            return raw.splitlines()[0].strip() if raw else None
    return None


def _enclosing_name(node, cfg):
    # qualified name of nearest enclosing class/func, walking up parents
    parts: list[str] = []
    cur = node
    while cur is not None:
        if cur.type in cfg["class"] or cur.type in cfg["func"]:
            n = cur.child_by_field_name("name")
            if n is not None:
                parts.append(n.text.decode("utf-8", "replace"))
        cur = cur.parent
    return ".".join(reversed(parts))


def _collect_calls(node, cfg, depth, enclosing):
    if depth > _MAX_AST_DEPTH:
        return
    for child in node.named_children:
        if child.type in cfg["call"]:
            fn = child.child_by_field_name(cfg["call_fn_field"])
            if fn is not None:
                callee = _last_identifier(fn)
                if callee:
                    yield RawCall(caller=_enclosing_name(child, cfg), callee=callee)
        yield from _collect_calls(child, cfg, depth + 1, enclosing)


def _last_identifier(fn) -> str:
    # foo() -> "foo"; obj.method() -> "method"; a.b.c() -> "c"
    txt = fn.text.decode("utf-8", "replace")
    return txt.split(".")[-1].split("(")[0].strip()


def _collect_imports(node, cfg, language):
    for child in node.named_children:
        if child.type in cfg["import"]:
            yield from _import_to_raw(child, language)
        # imports are module-level; no deep recursion needed, but descend one
        # level for wrappers like export_statement (TS) just in case
        elif child.type in ("export_statement",):
            yield from _collect_imports(child, cfg, language)


def _import_to_raw(node, language):
    if language == "python":
        if node.type == "import_statement":
            for n in node.named_children:
                # dotted_name or aliased_import
                name = n.child_by_field_name("name") if n.type == "aliased_import" else n
                yield RawImport(text=name.text.decode("utf-8", "replace"), level=0)
        elif node.type == "import_from_statement":
            mod = node.child_by_field_name("module_name")
            level = 0
            text = ""
            if mod is not None:
                t = mod.text.decode("utf-8", "replace")
                level = len(t) - len(t.lstrip("."))
                text = t.lstrip(".")
            else:
                # `from . import x` / `from .. import x`: count leading dots among children
                dots = sum(1 for c in node.children if c.type == ".")
                level = dots if dots else 1
            yield RawImport(text=text, level=level)
    else:
        # JS/TS: import ... from "source"
        src = node.child_by_field_name("source")
        if src is not None:
            spec = src.text.decode("utf-8", "replace").strip('\'"')
            yield RawImport(text=spec, level=0)
