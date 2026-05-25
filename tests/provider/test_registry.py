from poor_code.provider.registry import (
    DEFAULT_META,
    ModelMeta,
    ModelPricing,
    lookup,
)


def test_model_pricing_required_fields():
    p = ModelPricing(input_per_1m=3.0, output_per_1m=15.0)
    assert p.input_per_1m == 3.0
    assert p.output_per_1m == 15.0
    assert p.cache_read_per_1m is None
    assert p.cache_write_per_1m is None


def test_model_meta_with_pricing():
    p = ModelPricing(input_per_1m=3.0, output_per_1m=15.0)
    m = ModelMeta(
        model_id="claude-3-5-sonnet-20241022",
        context_size=200_000,
        max_output=8192,
        pricing=p,
    )
    assert m.model_id == "claude-3-5-sonnet-20241022"
    assert m.pricing is p


def test_model_meta_pricing_optional():
    m = ModelMeta(model_id="gpt-oss-120b", context_size=128_000, max_output=4096)
    assert m.pricing is None


def test_default_meta_shape():
    assert DEFAULT_META.context_size == 128_000
    assert DEFAULT_META.max_output == 4096
    assert DEFAULT_META.pricing is None


def test_lookup_exact_match():
    # Use a stable model id that should exist in any reasonable snapshot.
    # We don't assert specific numeric fields — those drift with models.dev.
    m = lookup("claude-3-5-sonnet-20241022")
    assert m.model_id == "claude-3-5-sonnet-20241022"
    assert m.context_size > 0
    assert m.pricing is not None


def test_lookup_longest_prefix_match():
    # A versioned model id that won't appear in models.dev verbatim
    # but whose base name does. Pick a real base like "gpt-4o".
    base = lookup("gpt-4o")
    assert base.model_id == "gpt-4o"  # sanity — base exists

    # Hypothetical date-suffixed variant — should fall back to "gpt-4o".
    versioned = lookup("gpt-4o-2099-12-31")
    assert versioned.model_id == "gpt-4o"
    assert versioned.context_size == base.context_size


def test_lookup_unknown_returns_default():
    m = lookup("this-model-definitely-does-not-exist-xyz")
    assert m is DEFAULT_META


def test_lookup_prefix_match_requires_dash_boundary():
    """A snapshot key must be followed by '-' or end-of-string to count as a
    prefix. Otherwise we'd mislabel e.g. 'gpt-4omg' as 'gpt-4o'."""
    # Sanity: gpt-4o is in the snapshot (used by other tests).
    assert lookup("gpt-4o").model_id == "gpt-4o"
    # False-positive trap: must NOT match.
    m = lookup("gpt-4omg")
    assert m is DEFAULT_META


def test_load_snapshot_handles_corrupt_json(tmp_path, monkeypatch):
    """If _models_snapshot.json is malformed, _load_snapshot returns {}
    so lookup() can still fall back to DEFAULT_META."""
    bad = tmp_path / "_models_snapshot.json"
    bad.write_text("{not json at all")
    from poor_code.provider import registry
    monkeypatch.setattr(registry, "_SNAPSHOT_PATH", bad)
    assert registry._load_snapshot() == {}


def test_load_snapshot_handles_missing_file(tmp_path, monkeypatch):
    """Missing snapshot file → {} (already handled, lock it in with a test)."""
    nonexistent = tmp_path / "does_not_exist.json"
    from poor_code.provider import registry
    monkeypatch.setattr(registry, "_SNAPSHOT_PATH", nonexistent)
    assert registry._load_snapshot() == {}


def test_lookup_preserves_zero_context_size_from_snapshot(monkeypatch):
    """When the snapshot reports context_size=0 (e.g., models.dev had no
    info), the lookup must preserve the 0 — NOT silently substitute
    DEFAULT_META.context_size. Callers (StatusFooter) treat 0 as 'unknown'
    and render '?/?' instead of a fake number."""
    from poor_code.provider import registry
    fake_snapshot = {"weird-model": {"context_size": 0, "max_output": 0}}
    monkeypatch.setattr(registry, "_SNAPSHOT", fake_snapshot)
    m = lookup("weird-model")
    assert m.context_size == 0
    assert m.max_output == 0
    assert m.model_id == "weird-model"  # not "<unknown>"
