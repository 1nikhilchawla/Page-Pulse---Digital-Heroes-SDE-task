from backend.models import AuditMetrics
from backend.scoring import score_report


def _metrics(**overrides) -> AuditMetrics:
    base = dict(
        http_status=200,
        response_time_ms=200,
        content_type="text/html; charset=utf-8",
        is_html=True,
        title="A Good Title Between Ten And Sixty Chars",
        meta_description="A meta description that sits comfortably inside the fifty to one hundred sixty character sweet spot for search snippets.",
        h1_count=1,
        images_total=4,
        images_missing_alt=0,
        images_missing_alt_examples=[],
        word_count=500,
    )
    base.update(overrides)
    return AuditMetrics(**base)


def test_ideal_page_scores_perfect():
    score = score_report(_metrics())
    assert score.total == 100
    assert score.grade == "A"


def test_missing_everything_scores_low():
    score = score_report(
        _metrics(
            response_time_ms=8000,
            title=None,
            meta_description=None,
            h1_count=0,
            images_total=5,
            images_missing_alt=5,
            word_count=20,
        )
    )
    assert score.total < 20
    assert score.grade in ("D", "F")


def test_no_images_does_not_penalize_accessibility():
    perfect = _metrics()
    no_images = _metrics(images_total=0, images_missing_alt=0)
    assert score_report(perfect).accessibility == score_report(no_images).accessibility == 25


def test_multiple_h1_is_penalized_but_not_as_much_as_zero():
    zero_h1 = score_report(_metrics(h1_count=0)).content
    one_h1 = score_report(_metrics(h1_count=1)).content
    many_h1 = score_report(_metrics(h1_count=3)).content
    assert zero_h1 < many_h1 < one_h1


def test_non_html_only_scores_performance_scaled_to_100():
    fast_non_html = _metrics(is_html=False, response_time_ms=200, content_type="application/pdf")
    score = score_report(fast_non_html)
    assert score.seo is None
    assert score.accessibility is None
    assert score.content is None
    assert score.total == 100  # performance=25 -> scaled *4


def test_grade_boundaries():
    assert score_report(_metrics(response_time_ms=0)).grade in ("A", "B")
    low = score_report(
        _metrics(
            response_time_ms=9000,
            title=None,
            meta_description=None,
            h1_count=0,
            images_total=10,
            images_missing_alt=10,
            word_count=10,
        )
    )
    assert low.grade == "F"
