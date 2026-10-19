from typing import Literal

from pydantic import BaseModel, Field


class FactItem(BaseModel):
    kind: Literal["name", "number", "date", "rank", "organisation", "place", "other"]
    source: str = Field(description="Exact form in the source article")
    target: str = Field(description="Exact form used in the translation")


class Flag(BaseModel):
    kind: Literal[
        "uncertain_term", "ambiguity", "glossary_gap", "source_issue", "honorific"
    ]
    source_span: str
    note: str


class DraftResult(BaseModel):
    detected_source_lang: Literal["ms", "en", "ar"]
    title: str
    summary: str = Field(description="Two sentences maximum")
    translation: str
    facts: list[FactItem]
    flags: list[Flag]
    significance_draft: str = Field(
        description="2-3 factual lines; a draft for the human to rewrite"
    )
    source_type: Literal["news_report", "official_statement", "opinion", "other"]


class ReviewIssue(BaseModel):
    severity: Literal["critical", "major", "minor"]
    category: Literal[
        "omission", "addition", "mistranslation", "terminology", "grammar", "style"
    ]
    source_span: str
    target_span: str
    explanation: str
    suggestion: str


class ReviewResult(BaseModel):
    issues: list[ReviewIssue]


class CheckResult(BaseModel):
    name: str  # "numbers", "glossary", "length_ratio", "fact_table"
    passed: bool
    details: list[str]  # human-readable findings


class Usage(BaseModel):
    """Token usage for one LLM call. Prices change, so cost is computed later, not here."""

    model: str  # the model that actually served the call (differs from the requested one after a fallback)
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    seconds: float = 0.0


class PipelineOutput(BaseModel):
    run_id: str  # UUID; the UI saves the human's edits against it
    source_lang: str  # resolved: ms, en or ar
    target_lang: str
    draft: DraftResult
    checks: list[CheckResult]
    review: ReviewResult
    usage: list[Usage]  # [draft, review]
    ai_seconds: float
