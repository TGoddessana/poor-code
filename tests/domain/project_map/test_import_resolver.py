from poor_code.domain.project_map.import_resolver import ImportResolver
from poor_code.domain.project_map.models import ParsedFile, RawImport

def _pf(path, *imports, language="python"):
    return ParsedFile(path=path, language=language, content_hash="sha256:x",
                      symbols=(), raw_imports=imports, raw_calls=(), parse_error=None)

def test_src_layout_absolute_resolves():
    files = (
        _pf("src/poor_code/app.py", RawImport(text="poor_code.messages", level=0)),
        _pf("src/poor_code/messages.py"),
    )
    imports, imported_by = ImportResolver().resolve(files)
    assert imports["src/poor_code/app.py"] == ("src/poor_code/messages.py",)
    assert imported_by["src/poor_code/messages.py"] == ("src/poor_code/app.py",)

def test_src_layout_package_init():
    files = (
        _pf("src/pkg/a.py", RawImport(text="pkg", level=0)),
        _pf("src/pkg/__init__.py"),
    )
    imports, _ = ImportResolver().resolve(files)
    assert imports["src/pkg/a.py"] == ("src/pkg/__init__.py",)

def test_non_src_layout_still_works():
    files = (_pf("a/b/c.py"), _pf("caller.py", RawImport(text="a.b.c", level=0)))
    imports, _ = ImportResolver().resolve(files)
    assert imports["caller.py"] == ("a/b/c.py",)

def test_relative_level_1():
    files = (_pf("pkg/sub/x.py"), _pf("pkg/sub/foo.py", RawImport(text="x", level=1)))
    imports, _ = ImportResolver().resolve(files)
    assert imports["pkg/sub/foo.py"] == ("pkg/sub/x.py",)

def test_relative_level_2():
    files = (_pf("pkg/other.py"), _pf("pkg/sub/foo.py", RawImport(text="other", level=2)))
    imports, _ = ImportResolver().resolve(files)
    assert imports["pkg/sub/foo.py"] == ("pkg/other.py",)

def test_externals_and_self_dropped():
    files = (_pf("a.py", RawImport(text="os", level=0), RawImport(text="a", level=0)),)
    imports, _ = ImportResolver().resolve(files)
    assert imports.get("a.py", ()) == ()

def test_js_relative_import():
    files = (
        _pf("web/app.ts", RawImport(text="./util", level=0), language="typescript"),
        _pf("web/util.ts", language="typescript"),
    )
    imports, imported_by = ImportResolver().resolve(files)
    assert imports["web/app.ts"] == ("web/util.ts",)
    assert imported_by["web/util.ts"] == ("web/app.ts",)

def test_dedup_order_preserved():
    files = (_pf("a.py"), _pf("b.py"),
             _pf("c.py", RawImport(text="b", level=0), RawImport(text="a", level=0),
                 RawImport(text="b", level=0)))
    imports, _ = ImportResolver().resolve(files)
    assert imports["c.py"] == ("b.py", "a.py")

def test_js_parent_traversal():
    files = (
        _pf("web/sub/app.ts", RawImport(text="../util", level=0), language="typescript"),
        _pf("web/util.ts", language="typescript"),
    )
    imports, _ = ImportResolver().resolve(files)
    assert imports["web/sub/app.ts"] == ("web/util.ts",)

def test_js_bare_specifier_is_external():
    files = (_pf("web/app.ts", RawImport(text="react", level=0), language="typescript"),)
    imports, _ = ImportResolver().resolve(files)
    assert imports.get("web/app.ts", ()) == ()

def test_js_index_fallback():
    files = (
        _pf("web/app.ts", RawImport(text="./components", level=0), language="typescript"),
        _pf("web/components/index.ts", language="typescript"),
    )
    imports, _ = ImportResolver().resolve(files)
    assert imports["web/app.ts"] == ("web/components/index.ts",)

def test_js_explicit_extension():
    files = (
        _pf("web/app.ts", RawImport(text="./util.ts", level=0), language="typescript"),
        _pf("web/util.ts", language="typescript"),
    )
    imports, _ = ImportResolver().resolve(files)
    assert imports["web/app.ts"] == ("web/util.ts",)
