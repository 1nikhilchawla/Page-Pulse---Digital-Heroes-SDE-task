"""Request/response schemas for the Page Pulse API.

Kept separate from analyzer.py so the "shape of the API" is readable in one
place, independent of how a report gets built.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class AuditRequest(BaseModel):
    url: str = Field(
        ...,
        min_length=1,
        max_length=2048,
        description="Any http(s) URL to audit, e.g. https://example.com/pricing",
        examples=["https://example.com"],
    )


class ScoreBreakdown(BaseModel):
    performance: int = Field(..., description="0-25, based on response time")
    seo: int | None = Field(None, description="0-25, title + meta description quality. null when not applicable (non-HTML)")
    accessibility: int | None = Field(None, description="0-25, share of <img> tags with alt text")
    content: int | None = Field(None, description="0-25, word count + heading structure")
    total: int = Field(..., description="0-100 composite Pulse Score")
    grade: str = Field(..., description="Letter grade A-F derived from total")
    label: str = Field(..., description="Human label, e.g. Excellent / Fair / Critical")


class AuditMetrics(BaseModel):
    http_status: int
    response_time_ms: int
    content_type: str | None = None
    is_html: bool
    title: str | None = None
    meta_description: str | None = None
    h1_count: int | None = None
    images_total: int | None = None
    images_missing_alt: int | None = None
    images_missing_alt_examples: list[str] = Field(default_factory=list)
    word_count: int | None = None


class AuditReport(BaseModel):
    requested_url: str
    resolved_url: str = Field(..., description="Final URL after redirects")
    fetched_at: str = Field(..., description="ISO-8601 UTC timestamp")
    metrics: AuditMetrics
    score: ScoreBreakdown
    warnings: list[str] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    error: str = Field(..., description="Stable machine-readable error code")
    message: str = Field(..., description="Human-readable explanation")
    details: dict = Field(default_factory=dict)
