"""Gate 2 (Meeting Q&A Prep & Ownership Check) schemas."""

from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field


class Gate2Question(BaseModel):
    id: str
    tag: str                                # e.g. "Load-Bearing Assumption", "Key Evidence", "Known Limitations & v2"
    prep_title: str                         # Crisp heading for the Meeting Q&A Prep Sheet
    question: str
    pages: list[int]                        # 1-indexed pages in the current revision
    page_fingerprints: list[str] = Field(default_factory=list)  # Composite hashes for v1->v2 preservation
    is_limitation: bool = False


class Gate2AnswerRecord(BaseModel):
    question_id: str
    answer_text: str = ""
    status: Literal["idle", "nudge", "verified"] = "idle"
    feedback: str = ""
    attempts: int = 0
    preserved_from_revision: int | None = None


class Gate2StartRequest(BaseModel):
    revision: int | None = None
    model_reasoning: str | None = None
    model_fast: str | None = None


class Gate2AnswerRequest(BaseModel):
    revision: int
    question_id: str
    answer_text: str
    model_fast: str | None = None


class Gate2StateResponse(BaseModel):
    session_id: str
    revision: int
    questions: list[Gate2Question]
    answers: dict[str, Gate2AnswerRecord]
    verified_count: int
    total_count: int
    all_verified: bool
    preserved_count: int = 0
    mode: Literal["live_gemini", "local_demo"] = "live_gemini"
    prep_sheet_markdown: str = ""


# --- Internal LLM Output Schemas for Gate 2 ---

class GeneratedGate2QuestionLLM(BaseModel):
    tag: str = Field(..., description="Short 2-4 word label, e.g. 'Load-Bearing Assumption', 'Key Visual Caveat', 'Late-Section Risk'")
    prep_title: str = Field(..., description="Short 4-7 word title for the Meeting Q&A Prep Sheet")
    question: str = Field(..., description="Crisp 1-sentence question voiced by the target reader; never petty trivia")
    pages: list[int] = Field(..., description="1-2 valid 1-indexed page numbers this question targets")


class Gate2QuestionsLLMOutput(BaseModel):
    questions: list[GeneratedGate2QuestionLLM] = Field(..., min_length=1, max_length=3)


class Gate2GradeLLMOutput(BaseModel):
    passed: bool = Field(..., description="True if rough-but-accurate, grounded answer showing real comprehension")
    feedback: str = Field(..., description="1 crisp sentence: affirming note if passed, or gentle specific nudge if vague/wrong")
