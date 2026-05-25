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
