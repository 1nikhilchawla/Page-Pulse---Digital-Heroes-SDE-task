"""Pulse Score: a 0-100 composite health score for a page.

Every sub-score below is a deliberately simple, explainable rule — not
because a fancier model wouldn't score pages "better," but because a
scoring rubric you can't explain in one sentence per line isn't
defensible in a report. Each function is documented with *why* that
threshold, so this doubles as the design-rationale writeup.

Weights (out of 100):
  performance    25  - how fast the page responded
  seo            25  - title + meta description presence/length
  accessibility  25  - share of <img> tags with real alt text
  content        25  - word count + heading structure

For non-HTML responses (a PDF, a JSON API, etc.) only `performance` is
meaningful, so the other three are left as None and the total is the
performance score alone, scaled to 100 — never a misleadingly low
absolute number from categories that don't apply.
"""
from __future__ import annotations

from .models import AuditMetrics, ScoreBreakdown


def _grade_and_label(total: int) -> tuple[str, str]:
    if total >= 90:
        return "A", "Excellent"
    if total >= 75:
        return "B", "Good"
    if total >= 60:
        return "C", "Fair"
    if total >= 40:
        return "D", "Poor"
    return "F", "Critical"


def _performance_score(response_time_ms: int) -> int:
    # Thresholds roughly follow common "perceived performance" bands
    # (sub-300ms feels instant, 3s+ is where users start bouncing).
    if response_time_ms <= 300:
        return 25
    if response_time_ms <= 800:
        return 20
    if response_time_ms <= 1500:
        return 15
    if response_time_ms <= 3000:
        return 10
    if response_time_ms <= 6000:
        return 5
    return 0


def _seo_score(title: str | None, meta_description: str | None) -> int:
    score = 0
    if title:
        score += 8
        if 10 <= len(title) <= 60:  # Google truncates titles past ~60 chars
            score += 4
    if meta_description:
        score += 8
        if 50 <= len(meta_description) <= 160:  # typical SERP snippet length
            score += 5
    return score


def _accessibility_score(images_total: int, images_missing_alt: int) -> int:
    if images_total == 0:
        return 25  # nothing to penalize
    coverage = (images_total - images_missing_alt) / images_total
    return round(coverage * 25)


def _content_score(word_count: int, h1_count: int) -> int:
    if word_count < 100:
        word_points = 5
    elif word_count < 300:
        word_points = 10
    else:
        word_points = 15

    if h1_count == 1:
        h1_points = 10
    elif h1_count == 0:
        h1_points = 3  # missing a primary heading hurts structure/SEO
    else:
        h1_points = 5  # multiple H1s: valid HTML5, but usually a structure smell

    return word_points + h1_points


def score_report(metrics: AuditMetrics) -> ScoreBreakdown:
    performance = _performance_score(metrics.response_time_ms)

    if not metrics.is_html:
        total = performance * 4  # scale the sole applicable category to /100
        grade, label = _grade_and_label(total)
        return ScoreBreakdown(
            performance=performance,
            seo=None,
            accessibility=None,
            content=None,
            total=total,
            grade=grade,
            label=label,
        )

    seo = _seo_score(metrics.title, metrics.meta_description)
    accessibility = _accessibility_score(metrics.images_total or 0, metrics.images_missing_alt or 0)
    content = _content_score(metrics.word_count or 0, metrics.h1_count or 0)
    total = performance + seo + accessibility + content
    grade, label = _grade_and_label(total)

    return ScoreBreakdown(
        performance=performance,
        seo=seo,
        accessibility=accessibility,
        content=content,
        total=total,
        grade=grade,
        label=label,
    )
