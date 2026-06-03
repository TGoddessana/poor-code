from poor_code.domain.session.models import CodeContext, FileExcerpt, GroundingStatus


def test_file_excerpt_defaults_not_truncated():
    ex = FileExcerpt(path="img.ppm", text="P6 800 600 255")
    assert ex.path == "img.ppm"
    assert ex.text == "P6 800 600 255"
    assert ex.truncated is False


def test_code_context_carries_summary_and_excerpts():
    cc = CodeContext(
        summary="greenfield node server; validate via curl /fib/10 == 55",
        excerpts=(FileExcerpt(path="img.ppm", text="P6 800 600", truncated=True),),
    )
    assert "curl" in cc.summary
    assert cc.excerpts[0].path == "img.ppm"
    assert cc.excerpts[0].truncated is True


def test_code_context_briefing_defaults_empty():
    cc = CodeContext()
    assert cc.summary == ""
    assert cc.excerpts == ()
    assert cc.grounding is GroundingStatus.NOT_FOUND
