"""Gate 1 (Pre-Flight Check) schemas: internal LLM contracts + public API report."""

from __future__ import annotations

from enum import Enum
from typing import Literal
from pydantic import BaseModel, Field

from app.schemas.document import DocFormat, DocPurpose, RevisionDiff, TargetPersona


class Severity(str, Enum):
    CRITICAL = "critical"
    VERIFY = "verify"


class IssueCategory(str, Enum):
    CONTRADICTION = "contradiction"
    CONTRADICTS_CHART = "contradicts_chart"
    MISSING_ASK = "missing_ask"
    CROSS_ORG_GAP = "cross_org_gap"
    UNSUPPORTED_LEAP = "unsupported_leap"
    WEAK_STORYLINE = "weak_storyline"
    MISSING_RISKS_FAQ = "missing_risks_faq"
    HOLLOW_STRATEGY = "hollow_strategy"


class Pass2IssueCategory(str, Enum):
    """Pass 2 does NOT emit WEAK_STORYLINE — Pass 1 is the single owner."""
    CONTRADICTION = "contradiction"
    CONTRADICTS_CHART = "contradicts_chart"
    MISSING_ASK = "missing_ask"
    CROSS_ORG_GAP = "cross_org_gap"
    UNSUPPORTED_LEAP = "unsupported_leap"
    MISSING_RISKS_FAQ = "missing_risks_faq"
    HOLLOW_STRATEGY = "hollow_strategy"


class EvidenceQuote(BaseModel):
    page: int
    quote: str = Field(..., description="Short exact excerpt or chart label from the cited page")


class IssueDisposition(BaseModel):
    status: Literal["intentional", "ignored"]
    note: str = ""


class Gate1Issue(BaseModel):
    id: str
    severity: Severity
    category: IssueCategory
    title: str
    pages: list[int]
    evidence: list[EvidenceQuote] = Field(default_factory=list)
    explanation: str
    suggested_fix: str
    disposition: IssueDisposition | None = None


# --- Internal LLM Output Schemas (kept separate from public Gate1Report) ---

class HeadingClassification(BaseModel):
    page: int
    text: str
    kind: Literal["action_title", "topic_label", "cover_or_divider"]


class GhostDeckLLMOutput(BaseModel):
    headings: list[HeadingClassification]
    title_only_storyline: str = Field(..., description="2-3 sentence summary of what a skimming reader gets from titles alone")
    storyline_holds: bool = Field(..., description="True if reading ONLY the titles conveys the core argument")
    gap_note: str | None = Field(default=None, description="Specific missing link if storyline_holds is False")


class ReconciliationEntry(BaseModel):
    metric_or_fact: str
    pages: list[int]
    values_seen: str
    is_conflict: bool


class Pass2RawIssue(BaseModel):
    severity: Severity
    category: Pass2IssueCategory
    title: str = Field(..., description="Crisp headline, <= 14 words")
    pages: list[int]
    evidence: list[EvidenceQuote] = Field(default_factory=list)
    explanation: str = Field(..., description="1-2 concise sentences")
    suggested_fix: str = Field(..., description="1 concrete actionable fix")


class ExecutiveSkim30s(BaseModel):
    perceived_purpose_and_ask: str
    remembered_takeaways: list[str] = Field(default_factory=list)
    stall_points: list[str] = Field(default_factory=list)


class Pass2LLMOutput(BaseModel):
    reconciliation_notes: list[ReconciliationEntry] = Field(
        default_factory=list,
        description="Bounded to <= 10 high-stakes numbers, dates, or headcount cross-checks across pages",
    )
    issues: list[Pass2RawIssue] = Field(default_factory=list)
    skim_30s: ExecutiveSkim30s


# --- Public API Request / Report Schemas ---

class GhostDeckResult(BaseModel):
    headings: list[HeadingClassification] = Field(default_factory=list)
    title_only_storyline: str = ""
    storyline_holds: bool = True
    gap_note: str | None = None
    error: str | None = None


class PageSummary(BaseModel):
    page_number: int
    status: Literal["clean", "verify", "critical"]
    word_count: int
    issue_ids: list[str] = Field(default_factory=list)


class PolishTip(BaseModel):
    page: int
    kind: Literal["weasel_word", "long_sentence", "unexpanded_acronym", "dense_slide"]
    snippet: str
    suggestion: str


class TokenUsage(BaseModel):
    prompt_tokens: int = 0
    output_tokens: int = 0
    thoughts_tokens: int = 0


class Gate1RunRequest(BaseModel):
    revision: int | None = None
    doc_format: DocFormat
    doc_purpose: DocPurpose = "decide"
    target_persona: TargetPersona = "leadership"
    custom_audience: str = ""
    creator_intent: str = ""
    model_reasoning: str | None = None
    model_fast: str | None = None


class Gate1RunCreated(BaseModel):
    run_id: str
    session_id: str
    revision: int
    status: Literal["queued", "running", "completed", "failed"]
    events_url: str


class DispositionRequest(BaseModel):
    status: Literal["intentional", "ignored", "clear"]
    note: str = ""


class CreatorIntentRequest(BaseModel):
    creator_intent: str


class Gate1Report(BaseModel):
    run_id: str
    session_id: str
    revision: int
    verdict: Literal["READY", "REVIEW_VERIFY", "FIX_CRITICAL_ISSUES", "NEEDS_REWORK"]
    doc_format: DocFormat
    doc_purpose: DocPurpose
    target_persona: TargetPersona
    custom_audience: str = ""
    creator_intent: str = ""
    model_used: str
    mode: Literal["live_gemini", "local_demo"] = "live_gemini"
    latency_ms: int
    pass1_ms: int = 0
    pass2_ms: int = 0
    usage: TokenUsage = Field(default_factory=TokenUsage)
    issues: list[Gate1Issue] = Field(default_factory=list)
    ghost_deck: GhostDeckResult | None = None
    skim_30s: ExecutiveSkim30s
    pages: list[PageSummary] = Field(default_factory=list)
    polish_tips: list[PolishTip] = Field(default_factory=list)
    revision_diff: RevisionDiff | None = None
    invalid_citations_dropped: int = 0
