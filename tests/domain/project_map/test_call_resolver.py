from poor_code.domain.project_map.call_resolver import CallResolver
from poor_code.domain.project_map.models import ParsedFile, RawCall, Symbol, SymbolKind

def _sym(name, kind=SymbolKind.FUNCTION):
    return Symbol(name=name, kind=kind, lineno=1, signature=None, doc=None, calls=(), called_by=())

def _pf(path, symbols, *calls):
    return ParsedFile(path=path, language="python", content_hash="sha256:x",
                      symbols=tuple(symbols), raw_imports=(), raw_calls=tuple(calls),
                      parse_error=None)

def test_same_file_resolution():
    pf = _pf("a.py", [_sym("Foo.bar", SymbolKind.METHOD), _sym("helper")],
             RawCall(caller="Foo.bar", callee="helper"))
    calls, called_by = CallResolver().resolve((pf,))
    assert calls[("a.py", "Foo.bar")] == ("a.py::helper",)
    assert called_by[("a.py", "helper")] == ("a.py::Foo.bar",)

def test_unique_cross_file():
    a = _pf("a.py", [_sym("caller")], RawCall(caller="caller", callee="uniquefn"))
    b = _pf("b.py", [_sym("uniquefn")])
    calls, _ = CallResolver().resolve((a, b))
    assert calls[("a.py", "caller")] == ("b.py::uniquefn",)

def test_ambiguous_cross_file_dropped():
    a = _pf("a.py", [_sym("caller")], RawCall(caller="caller", callee="dup"))
    b = _pf("b.py", [_sym("dup")])
    c = _pf("c.py", [_sym("dup")])
    calls, _ = CallResolver().resolve((a, b, c))
    assert calls.get(("a.py", "caller"), ()) == ()

def test_unresolved_dropped():
    a = _pf("a.py", [_sym("caller")], RawCall(caller="caller", callee="nowhere"))
    calls, _ = CallResolver().resolve((a,))
    assert calls.get(("a.py", "caller"), ()) == ()

def test_nested_caller_not_a_symbol_produces_no_dangling_edges():
    # 'outer.inner' is not a defined symbol (only 'outer' is); a call attributed
    # to it must NOT create a forward edge NOR a dangling called_by edge.
    pf = _pf("a.py", [_sym("outer"), _sym("helper")],
             RawCall(caller="outer.inner", callee="helper"))
    calls, called_by = CallResolver().resolve((pf,))
    assert calls.get(("a.py", "outer.inner"), ()) == ()
    assert called_by.get(("a.py", "helper"), ()) == ()

def test_real_caller_still_resolves():
    # sanity: a real symbol caller still produces both edges
    pf = _pf("a.py", [_sym("outer"), _sym("helper")],
             RawCall(caller="outer", callee="helper"))
    calls, called_by = CallResolver().resolve((pf,))
    assert calls[("a.py", "outer")] == ("a.py::helper",)
    assert called_by[("a.py", "helper")] == ("a.py::outer",)
