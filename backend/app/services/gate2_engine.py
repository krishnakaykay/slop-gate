"""Gate 2 (Meeting Q&A Prep & Ownership Check) engine.

Implements:
- High-relevance hotspot question generation (2-3 targeted questions + 1 Known Limitations card)
- Page-fingerprint binding & v1 -> v2 delta preservation of verified answers
- Smart Verbatim-Retype Guard (strips numbers/stopwords; requires >=7 contiguous tokens)
- Light / Encouraging answer validation (live Gemini or local heuristic fallback)
- Copyable Meeting Q&A Prep Sheet Markdown compiler
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Literal

from app.config import settings
from app.prompts.gate2_questions import (
    GATE2_GRADING_SYSTEM_PROMPT,
    build_gate2_question_system_prompt,
)
from app.schemas.document import DocFormat, DocPurpose, PageArtifact, TargetPersona
from app.schemas.gate1 import Gate1Report
from app.schemas.gate2 import (
    Gate2AnswerRecord,
    Gate2GradeLLMOutput,
    Gate2Question,
    Gate2QuestionsLLMOutput,
    Gate2StateResponse,
)
from app.services.llm_provider import GeminiProvider, ImagePart, LLMProvider, TextPart

logger = logging.getLogger(__name__)

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "then", "else", "to", "of", "in", "on", "for",
    "with", "at", "by", "from", "up", "about", "into", "over", "after", "is", "are", "was",
    "were", "be", "been", "being", "have", "has", "had", "do", "does", "did", "will", "would",
    "shall", "should", "can", "could", "may", "might", "must", "this", "that", "these", "those",
    "it", "its", "we", "our", "us", "they", "their", "them", "you", "your", "as", "not", "no",
    "so", "than", "too", "very", "just", "all", "any", "both", "each", "more", "most", "other",
}

GENERIC_LIMITATION_RE = re.compile(
    r"^\s*(looks?\s+good|nothing(\s+else)?|no\s+issues?|none|n/?a|perfect|all\s+good|no\s+limitations?|no\s+changes?|looks?\s+solid|everything\s+is\s+(good|clear|fine))\b",
    re.I,
)

EMPTY_BUZZWORD_RE = re.compile(
    r"\b(align cross-functionally|drive synergy|ensure alignment|holistic approach|leverage best practices|streamline operations|maximize value)\b",
    re.I,
)


def composite_page_fingerprint(page: PageArtifact) -> str:
    return f"{page.fingerprint.text_hash[:16]}:{page.fingerprint.embedded_img_hash[:16]}"


def _content_tokens(text: str) -> list[str]:
    """Extract lowercase alpha tokens stripping numbers, currency, and stopwords."""
    raw = re.findall(r"[a-zA-Z]{3,}", text.lower())
    return [w for w in raw if w not in STOPWORDS]


def is_verbatim_retype(answer_text: str, source_texts: list[str], *, min_run: int = 7) -> bool:
    """Detect mechanical visual retyping while ignoring numbers, acronyms, and short technical phrases."""
    ans_toks = _content_tokens(answer_text)
    if len(ans_toks) < min_run:
        return False

    src_blob_tokens = _content_tokens(" ".join(source_texts))
    if len(src_blob_tokens) < min_run:
        return False

    # Build set of contiguous `min_run`-grams from source pages
    src_windows = {
        tuple(src_blob_tokens[i : i + min_run])
        for i in range(len(src_blob_tokens) - min_run + 1)
    }
    for j in range(len(ans_toks) - min_run + 1):
        if tuple(ans_toks[j : j + min_run]) in src_windows:
            return True
    return False


def is_generic_limitation(answer_text: str) -> bool:
    clean = answer_text.strip()
    if len(clean.split()) < 6:
        return True
    if GENERIC_LIMITATION_RE.search(clean) and len(clean.split()) < 14:
        return True
    return False


def compile_prep_sheet_markdown(
    *,
    filename: str,
    questions: list[Gate2Question],
    answers: dict[str, Gate2AnswerRecord],
    gate1_report: Gate1Report | None = None,
) -> str:
    lines = [f"# Meeting Q&A Prep Sheet — {filename}", ""]
    if gate1_report and gate1_report.creator_intent:
        lines.append(f"**Stated Goal / Takeaway:** {gate1_report.creator_intent}")
        lines.append("")

    for q in questions:
        ans = answers.get(q.id)
        prefix = "★ " if q.is_limitation else ""
        page_str = ", ".join(f"P{p}" for p in q.pages)
        lines.append(f"### {prefix}{q.prep_title} ({page_str})")
        lines.append(f"*Q: {q.question}*")
        if ans and ans.answer_text.strip():
            lines.append(ans.answer_text.strip())
        else:
            lines.append("_(Pending your note)_")
        lines.append("")

    if gate1_report:
        noted = [i for i in gate1_report.issues if i.disposition is not None]
        if noted:
            lines.append("## Logged Pre-Flight Decisions (Intentional / Deferred)")
            for iss in noted:
                pstr = ", ".join(f"P{p}" for p in iss.pages)
                label = "Intentional" if iss.disposition.status == "intentional" else "Ignored for now"
                lines.append(f"- **{iss.title}** ({pstr}) — *{label}:* {iss.disposition.note}")
            lines.append("")

    return "\n".join(lines).strip()


def build_gate2_response(
    *,
    session_id: str,
    revision: int,
    filename: str,
    mode: Literal["live_gemini", "local_demo"],
    questions: list[Gate2Question],
    answers: dict[str, Gate2AnswerRecord],
    preserved_count: int,
    gate1_report: Gate1Report | None = None,
) -> Gate2StateResponse:
    verified = sum(1 for q in questions if answers.get(q.id) and answers[q.id].status == "verified")
    total = len(questions)
    md = compile_prep_sheet_markdown(
        filename=filename,
        questions=questions,
        answers=answers,
        gate1_report=gate1_report,
    )
    return Gate2StateResponse(
        session_id=session_id,
        revision=revision,
        questions=questions,
        answers=answers,
        verified_count=verified,
        total_count=total,
        all_verified=(total > 0 and verified == total),
        preserved_count=preserved_count,
        mode=mode,
        prep_sheet_markdown=md,
    )


def _known_limitation_card(pages: list[PageArtifact]) -> Gate2Question:
    first_p = 1
    last_p = len(pages)
    target_pages = [first_p] if last_p == 1 else [first_p, last_p]
    fp_by_p = {p.page_number: composite_page_fingerprint(p) for p in pages}
    return Gate2Question(
        id="q-limitation",
        tag="Known Limitations & v2",
        prep_title="Known Limitation / Next Iteration",
        question="Now that you've reviewed the full document: what is one specific limitation, blind spot, or improvement you want to strengthen in the next iteration?",
        pages=target_pages,
        page_fingerprints=[fp_by_p[p] for p in target_pages],
        is_limitation=True,
    )


def _generate_local_demo_questions(
    *,
    pages: list[PageArtifact],
    target_count: int,
    target_persona: TargetPersona,
) -> list[Gate2Question]:
    """High-relevance deterministic questions for Local Demo Mode (no API key required)."""
    full_lower = "\n".join(p.extracted_text for p in pages).lower()
    fp_by_p = {p.page_number: composite_page_fingerprint(p) for p in pages}
    n = len(pages)

    def mk(qid: str, tag: str, prep_title: str, question: str, pnums: list[int]) -> Gate2Question:
        valid = [p for p in pnums if 1 <= p <= n] or [1]
        return Gate2Question(
            id=qid,
            tag=tag,
            prep_title=prep_title,
            question=question,
            pages=valid,
            page_fingerprints=[fp_by_p[p] for p in valid],
            is_limitation=False,
        )

    out: list[Gate2Question] = []

    if "opex bridge" in full_lower and "109%" in full_lower:
        out = [
            mk(
                "q-1",
                "Load-Bearing Financial Trade-Off",
                "Defending the +$1.44M AE OpEx Ask",
                "If the Board pushes back on the +$1.44M H1 Sales OpEx variance for the 8 new Enterprise AEs, what concrete pacing or stop-loss trigger protects cash runway?",
                [6, 13],
            ),
            mk(
                "q-2",
                "Evidence & Cohort Nuance",
                "Framing 109% Organic NRR vs. Renewals",
                "How will you explain the difference between 109% organic NRR and the $1.1M Q1 renewal pull-forward so the Board trusts our Enterprise retention trajectory?",
                [2, 14],
            ),
            mk(
                "q-3",
                "Late-Section Operational Risk",
                "EU Frankfurt Slip Contingency",
                "Is the $1.6M DACH pipeline gated on Frankfurt hosting committed inside the $58M FY27 target—and what is your fallback if EU residency slips 6 weeks?",
                [10, 11],
            ),
        ]
    elif "tier-1" in full_lower and "copilot" in full_lower:
        out = [
            mk(
                "q-1",
                "Cross-Team Opportunity Cost",
                "Search Infra 14-Week Loan Trade-Off",
                "Which Search Infra roadmap deliverable slips while 2 ML platform engineers are loaned for this pilot, and what is the contingency if they are pulled back early?",
                [1],
            ),
            mk(
                "q-2",
                "Operational Risk & Fallback",
                "Aug 30 No-Go & BPO Notice Fallback",
                "If the pilot misses the 7.3 min handle-time gate on Aug 30, how does that affect your Sep 1 BPO contract notice deadline and total sunk cost?",
                [2],
            ),
        ]
    elif "project helios" in full_lower and "lakehouse" in full_lower:
        out = [
            mk(
                "q-1",
                "Load-Bearing Timeline Risk",
                "90-Day Archival Buffer & May 15 Gate",
                "If Finance delays budget approval past May 15, how many weeks before the 94% cluster write-throttling ceiling actually hits daily Finance close?",
                [1, 2],
            ),
            mk(
                "q-2",
                "Ruled-Out Alternative",
                "Why Managed Lakehouse Beats Vertical Scale",
                "If leadership balks at the 3-week Oct feature freeze, why shouldn't we just buy Option B (vertical hardware upgrade) to avoid migration disruption?",
                [3, 5],
            ),
            mk(
                "q-3",
                "Cutover Safety & Rollback",
                "Finance KPI Parity & Rollback Plan",
                "What happens if shadow validation on Oct 12 shows >0.01% variance on a core Finance metric—how do you execute rollback without losing Q4 readiness?",
                [4, 6],
            ),
        ]
    elif "wal" in full_lower and "fdatasync" in full_lower:
        out = [
            mk(
                "q-1",
                "Latency Trade-Off Defense",
                "Justifying +2.5ms Median Write Trade-Off",
                "Why is trading +2.5ms higher p50 write latency for 3x throughput and lower p99 acceptable for checkout, and how do low-traffic regions avoid unnecessary batch wait?",
                [1],
            ),
            mk(
                "q-2",
                "Crash Recovery & Rollback",
                "Partial WAL Tear & Instant Flag Revert",
                "If a production node crashes mid-batch during holiday peak, what guarantees zero lost acknowledged ledger writes—and how fast can on-call revert?",
                [1, 2],
            ),
        ]
    elif "tax-svc" in full_lower and "postmortem" in full_lower:
        out = [
            mk(
                "q-1",
                "Systemic Prevention Mechanism",
                "Stopping Future Cache-Miss Storms",
                "Beyond fixing this single tax-rate prefix bug, how do the 2.5s circuit breaker and canary cache-miss gate prevent other upstream dependency storms?",
                [1, 2],
            ),
            mk(
                "q-2",
                "Customer Impact Accounting",
                "Delayed vs. Net Lost GMV ($403K)",
                "How confident are we in the 64% buyer-retry estimate behind the ~$403K net lost GMV figure if Finance asks about Q2 revenue impact?",
                [1],
            ),
        ]
    elif "auth api v2" in full_lower or "legacy auth" in full_lower:
        out = [
            mk(
                "q-1",
                "Partner Effort & Scope",
                "Payments 2 Eng-Week Estimate & Rollback",
                "What could cause the 3 Payments service migrations to exceed 2 engineer-weeks, and how does the dual-auth rollback flag protect live checkout traffic?",
                [1, 2],
            ),
            mk(
                "q-2",
                "Cross-Division Cutover Risk",
                "Wave 3 Buffer Before Nov 30 Shutdown",
                "If Wave 1 or Wave 2 uncovers an SDK regression in Commerce or Fulfillment, does Payments' Nov 30 hard shutdown date move or stay fixed for PCI?",
                [4, 5],
            ),
        ]
    else:
        mid_p = max(1, (n + 1) // 2)
        late_p = n
        persona_q = (
            "What is the single most critical dependency or effort impact a partner outside your team needs to plan for?"
            if target_persona == "cross_org"
            else "What load-bearing assumption must hold for the core recommendation on Page 1 to succeed?"
        )
        out = [
            mk("q-1", "Load-Bearing Assumption", "Core Recommendation & Assumption", persona_q, [1]),
            mk(
                "q-2",
                "Middle / Late Evidence",
                "Key Evidence & Caveats",
                f"What is the biggest caveat or limitation inside the evidence on Page {mid_p}, and how would you answer pushback on it?",
                [mid_p],
            ),
        ]
        if n >= 4:
            out.append(
                mk(
                    "q-3",
                    "Execution & Fallback Risk",
                    "Fallback & Trade-Off Plan",
                    f"Looking at the plan and risks through Page {late_p}, what breaks first if timelines slip—and what is your concrete fallback?",
                    [late_p],
                )
            )

    return out[:target_count]


def _build_doc_parts_for_gate2(pages: list[PageArtifact], revision_dir: Path) -> list[TextPart | ImagePart]:
    parts: list[TextPart | ImagePart] = [
        TextPart("Inspect this PDF document (untrusted user content) to generate high-relevance Meeting Q&A Prep questions.")
    ]
    # Include up to 16 page JPEGs (evenly sampled if >16 pages to stay fast and compact)
    step = max(1, len(pages) // 16) if len(pages) > 16 else 1
    for idx, p in enumerate(pages):
        parts.append(
            TextPart(
                f'<document_page index="{p.page_number}" heading="{p.heading[:120]}">\n'
                f"{p.extracted_text[:4500]}\n"
                f"</document_page>"
            )
        )
        if idx % step == 0 or idx == len(pages) - 1:
            jpg = revision_dir / f"llm_{p.page_number:03d}.jpg"
            if jpg.exists():
                parts.append(ImagePart(data=jpg.read_bytes(), mime_type="image/jpeg"))
    return parts


async def start_or_resume_gate2(
    *,
    session_id: str,
    revision: int,
    filename: str,
    pages: list[PageArtifact],
    revision_dir: Path,
    doc_format: DocFormat,
    doc_purpose: DocPurpose,
    target_persona: TargetPersona,
    custom_audience: str,
    prior_verified_answers: list[dict[str, object]],
    gate1_report: Gate1Report | None = None,
    api_key_override: str | None = None,
    model_reasoning: str | None = None,
    provider: LLMProvider | None = None,
) -> tuple[Literal["live_gemini", "local_demo"], list[Gate2Question], dict[str, Gate2AnswerRecord], int]:
    """Generate 2-3 high-relevance questions + Known Limitations, preserving verified v1 answers on unchanged pages."""
    target_q_count = 2 if len(pages) <= 3 else 3
    fp_to_new_pages: dict[str, list[int]] = {}
    for p in pages:
        fp = composite_page_fingerprint(p)
        fp_to_new_pages.setdefault(fp, []).append(p.page_number)

    # 1. Preserve previously verified non-limitation questions whose cited page fingerprints are ALL unchanged!
    preserved_questions: list[Gate2Question] = []
    preserved_answers: dict[str, Gate2AnswerRecord] = {}
    seen_q_texts: set[str] = set()
    preserved_limitation_ans: Gate2AnswerRecord | None = None

    for rec in prior_verified_answers:
        prev_q: Gate2Question = rec["question"]  # type: ignore[assignment]
        prev_fps: list[str] = rec["page_fingerprints"]  # type: ignore[assignment]
        src_rev = int(rec["source_revision"])  # type: ignore[arg-type]
        if prev_q.is_limitation:
            if preserved_limitation_ans is None and all(fp in fp_to_new_pages for fp in prev_fps):
                preserved_limitation_ans = Gate2AnswerRecord(
                    question_id="q-limitation",
                    answer_text=str(rec["answer_text"]),
                    status="verified",
                    feedback=str(rec.get("feedback") or "Preserved from prior revision."),
                    attempts=1,
                    preserved_from_revision=src_rev,
                )
            continue

        if prev_q.question in seen_q_texts or not prev_fps:
            continue
        if all(fp in fp_to_new_pages for fp in prev_fps):
            remapped_pages: list[int] = []
            for fp in prev_fps:
                pnum = fp_to_new_pages[fp][0]
                if pnum not in remapped_pages:
                    remapped_pages.append(pnum)
            new_qid = f"q-{len(preserved_questions) + 1}"
            remapped_q = Gate2Question(
                id=new_qid,
                tag=prev_q.tag,
                prep_title=prev_q.prep_title,
                question=prev_q.question,
                pages=remapped_pages,
                page_fingerprints=prev_fps,
                is_limitation=False,
            )
            preserved_questions.append(remapped_q)
            preserved_answers[new_qid] = Gate2AnswerRecord(
                question_id=new_qid,
                answer_text=str(rec["answer_text"]),
                status="verified",
                feedback=str(rec.get("feedback") or "Preserved from unchanged pages."),
                attempts=1,
                preserved_from_revision=src_rev,
            )
            seen_q_texts.add(prev_q.question)
            if len(preserved_questions) >= target_q_count:
                break

    needed = max(0, target_q_count - len(preserved_questions))
    effective_key = (api_key_override or settings.effective_gemini_key).strip()
    m_reasoning = (model_reasoning or settings.llm_model_reasoning).strip()

    mode: Literal["live_gemini", "local_demo"] = "live_gemini"
    if provider is None and effective_key:
        provider = GeminiProvider(api_key=effective_key)
    if provider is None:
        mode = "local_demo"

    fresh_questions: list[Gate2Question] = []
    if needed > 0:
        if provider is None:
            cand = _generate_local_demo_questions(
                pages=pages,
                target_count=target_q_count,
                target_persona=target_persona,
            )
            for cq in cand:
                if cq.question not in seen_q_texts and len(fresh_questions) < needed:
                    cq.id = f"q-{len(preserved_questions) + len(fresh_questions) + 1}"
                    fresh_questions.append(cq)
                    seen_q_texts.add(cq.question)
        else:
            sys_prompt = build_gate2_question_system_prompt(
                doc_format=doc_format,
                doc_purpose=doc_purpose,
                target_persona=target_persona,
                custom_audience=custom_audience,
                target_question_count=needed,
            )
            parts = _build_doc_parts_for_gate2(pages, revision_dir)
            if preserved_questions:
                already = "\n".join(f"- {q.question}" for q in preserved_questions)
                parts.append(TextPart(f"\nDo NOT duplicate these already-answered questions:\n{already}"))
            parsed, _usage = await provider.generate_structured(
                model=m_reasoning,
                system_prompt=sys_prompt,
                parts=parts,
                response_schema=Gate2QuestionsLLMOutput,
                temperature=0.2,
                max_output_tokens=8192,
                timeout_seconds=60,
            )
            fp_by_p = {p.page_number: composite_page_fingerprint(p) for p in pages}
            for item in parsed.questions[:needed]:
                valid_pages = [p for p in item.pages if 1 <= p <= len(pages)] or [1]
                valid_pages = list(dict.fromkeys(valid_pages))[:2]
                qid = f"q-{len(preserved_questions) + len(fresh_questions) + 1}"
                fresh_questions.append(
                    Gate2Question(
                        id=qid,
                        tag=item.tag.strip(),
                        prep_title=item.prep_title.strip(),
                        question=item.question.strip(),
                        pages=valid_pages,
                        page_fingerprints=[fp_by_p[p] for p in valid_pages],
                        is_limitation=False,
                    )
                )

    all_questions = [*preserved_questions, *fresh_questions, _known_limitation_card(pages)]
    answers: dict[str, Gate2AnswerRecord] = {}
    for q in all_questions:
        if q.id in preserved_answers:
            answers[q.id] = preserved_answers[q.id]
        elif q.is_limitation and preserved_limitation_ans is not None:
            answers[q.id] = preserved_limitation_ans
        else:
            answers[q.id] = Gate2AnswerRecord(question_id=q.id, status="idle")

    preserved_count = sum(1 for a in answers.values() if a.preserved_from_revision is not None)
    return mode, all_questions, answers, preserved_count


async def evaluate_gate2_answer(
    *,
    question: Gate2Question,
    answer_text: str,
    prior_attempts: int,
    pages: list[PageArtifact],
    api_key_override: str | None = None,
    model_fast: str | None = None,
    provider: LLMProvider | None = None,
) -> Gate2AnswerRecord:
    """Evaluate a creator's typed own-words answer with Verbatim Guard + Light/Encouraging grading."""
    clean = " ".join(answer_text.strip().split())
    attempts = prior_attempts + 1
    words = clean.split()

    # 1. Minimum substance check
    if len(words) < 6:
        return Gate2AnswerRecord(
            question_id=question.id,
            answer_text=answer_text.strip(),
            status="nudge",
            feedback="Jot at least 1 concrete sentence (rough notes are totally fine) naming the key driver, caveat, or fallback.",
            attempts=attempts,
        )

    # 2. Known Limitations boilerplate guard
    if question.is_limitation and is_generic_limitation(clean):
        return Gate2AnswerRecord(
            question_id=question.id,
            answer_text=answer_text.strip(),
            status="nudge",
            feedback="Even sharp docs have an unvalidated assumption or data gap — name 1 specific caveat you would tighten in v2.",
            attempts=attempts,
        )

    # 3. Smart Verbatim-Retype Guard (contiguous >=7 non-stopword tokens from cited pages)
    page_map = {p.page_number: p.extracted_text for p in pages}
    cited_texts = [page_map.get(p, "") for p in question.pages]
    if not question.is_limitation and is_verbatim_retype(clean, cited_texts):
        return Gate2AnswerRecord(
            question_id=question.id,
            answer_text=answer_text.strip(),
            status="nudge",
            feedback="Very close to the PDF's exact phrasing — try restating the core idea in your own quick words.",
            attempts=attempts,
        )

    # 4. Buzzword-only guard (on first attempt)
    if attempts == 1 and EMPTY_BUZZWORD_RE.search(clean) and len(words) < 16:
        return Gate2AnswerRecord(
            question_id=question.id,
            answer_text=answer_text.strip(),
            status="nudge",
            feedback="That sounds a bit high-level — name the specific number, dependency, or concrete fallback from your document.",
            attempts=attempts,
        )

    # 5. Live Gemini Light/Encouraging grading (or local heuristic acceptance)
    effective_key = (api_key_override or settings.effective_gemini_key).strip()
    m_fast = (model_fast or settings.llm_model_fast).strip()
    if provider is None and effective_key:
        provider = GeminiProvider(api_key=effective_key)

    if provider is not None:
        excerpt = "\n\n".join(
            f"<document_page index=\"{p}\">\n{page_map.get(p, '')[:2500]}\n</document_page>"
            for p in question.pages
        )
        prompt = (
            f"Question Tag: {question.tag}\n"
            f"Is Known-Limitations Prompt: {str(question.is_limitation).lower()}\n"
            f"Question Asked: {question.question}\n"
            f"Attempt Number: {attempts}\n\n"
            f"Relevant Document Excerpt:\n{excerpt}\n\n"
            f"<user_answer>\n{clean}\n</user_answer>"
        )
        try:
            graded, _u = await provider.generate_structured(
                model=m_fast,
                system_prompt=GATE2_GRADING_SYSTEM_PROMPT,
                parts=[TextPart(prompt)],
                response_schema=Gate2GradeLLMOutput,
                temperature=0.1,
                max_output_tokens=4096,
                timeout_seconds=45,
            )
            # Enforce "at most 1 gentle follow-up" guarantee on sincere revised answers
            passed = graded.passed or (attempts >= 2 and len(words) >= 8)
            return Gate2AnswerRecord(
                question_id=question.id,
                answer_text=answer_text.strip(),
                status="verified" if passed else "nudge",
                feedback=graded.feedback.strip(),
                attempts=attempts,
            )
        except Exception as exc:
            logger.warning("Gate 2 LLM grading fallback due to error: %s", exc)

    # Local encouraging acceptance when no API key is configured
    fb = (
        "Sharp, concrete blind spot — saved as a Speaker Prep note."
        if question.is_limitation
        else "Clear, grounded defense — added to your Meeting Q&A Prep Sheet."
    )
    return Gate2AnswerRecord(
        question_id=question.id,
        answer_text=answer_text.strip(),
        status="verified",
        feedback=fb,
        attempts=attempts,
    )
