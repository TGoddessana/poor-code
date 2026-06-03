from poor_code.domain.harness.nodes.explorer import _EXTRACT_SYSTEM


def test_extract_prompt_is_findings_only():
    low = _EXTRACT_SYSTEM.lower()
    # validation-design and invented data facts removed
    assert "command that actually validates" not in low
    assert "file dimensions" not in low
    assert "what the request actually requires" not in low
    # recon framing retained / reinforced
    assert "observed" in low
