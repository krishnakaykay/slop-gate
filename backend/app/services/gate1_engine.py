"""Gate 1 (Pre-Flight Check) orchestration engine.

Implements:
- Pass 1 (Isolated Title-Only Ghost-Deck, single owner of WEAK_STORYLINE)
- Pass 2 (Multimodal Page JPEGs + Exact Extracted Text, Reasoning tier)
- Post-LLM Grounding Validator (bounds check, hard-strip MISSING_ASK on inform)
- Total, mutually exclusive Verdict State Machine
- Clean Local Demo fallback when GEMINI_API_KEY is not configured
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from pathlib import Path
from typing import Callable, Awaitable, Literal

from app.config import settings
from app.prompts.gate1_audit import build_gate1_system_prompt
from app.prompts.ghost_deck import GHOST_DECK_SYSTEM_PROMPT, build_ghost_deck_prompt
from app.schemas.document import DocFormat, DocPurpose, PageArtifact, RevisionDiff, TargetPersona
from app.schemas.gate1 import (
    EvidenceQuote,
    ExecutiveSkim30s,
    Gate1Issue,
    Gate1Report,
    GhostDeckLLMOutput,
    GhostDeckResult,
    HeadingClassification,
    IssueCategory,
    PageSummary,
    Pass2LLMOutput,
    Severity,
    TokenUsage,
)
from app.services.llm_provider import GeminiProvider, ImagePart, LLMProvider, TextPart
from app.services.polish_linters import run_polish_linters

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[str, dict[str, object]], Awaitable[None]]


def compute_verdict(
    issues: list[Gate1Issue],
) -> Literal["READY", "REVIEW_VERIFY", "FIX_CRITICAL_ISSUES", "NEEDS_REWORK"]:
    """Total, mutually exclusive verdict state machine over unresolved non-Polish issues."""
    critical = [i for i in issues if i.severity == Severity.CRITICAL and i.disposition is None]
    verify = [i for i in issues if i.severity == Severity.VERIFY and i.disposition is None]
    has_hollow = any(i.category == IssueCategory.HOLLOW_STRATEGY for i in verify)

    if len(critical) >= 3:
        return "NEEDS_REWORK"
    if len(critical) >= 1 and (has_hollow or len(verify) >= 3):
        return "NEEDS_REWORK"
    if len(critical) >= 1:
        return "FIX_CRITICAL_ISSUES"
    if has_hollow and len(verify) >= 2:
        return "NEEDS_REWORK"
    return "READY"


def build_page_summaries(
    page_count: int,
    word_counts: dict[int, int],
    issues: list[Gate1Issue],
) -> list[PageSummary]:
    """Deterministically compute per-page status and linked issue IDs."""
    summaries: list[PageSummary] = []
    for pno in range(1, page_count + 1):
        linked = [i for i in issues if pno in i.pages]
        active = [i for i in linked if i.disposition is None]
        if any(i.severity == Severity.CRITICAL for i in active):
            st: Literal["clean", "verify", "critical"] = "critical"
        elif any(i.severity == Severity.VERIFY for i in active):
            st = "verify"
        else:
            st = "clean"
        summaries.append(
            PageSummary(
                page_number=pno,
                status=st,
                word_count=word_counts.get(pno, 0),
                issue_ids=[i.id for i in linked],
            )
        )
    return summaries


def validate_and_normalize_issues(
    raw_issues: list[Gate1Issue],
    *,
    page_count: int,
    doc_purpose: DocPurpose,
) -> tuple[list[Gate1Issue], int]:
    """Post-LLM grounding validator:
    - Hard-strips MISSING_ASK when doc_purpose == 'inform'.
    - Drops out-of-range page citations and counts invalid citations.
    - Allows same-page contradictions (e.g., two paragraphs on Page 1).
    - Orders CRITICAL before VERIFY and assigns deterministic IDs.
    """
    invalid_dropped = 0
    cleaned: list[Gate1Issue] = []

    for idx, issue in enumerate(raw_issues, start=1):
        if doc_purpose == "inform" and issue.category == IssueCategory.MISSING_ASK:
            continue

        valid_pages: list[int] = []
        for p in issue.pages:
            if 1 <= p <= page_count:
                if p not in valid_pages:
                    valid_pages.append(p)
            else:
                invalid_dropped += 1

        valid_ev: list[EvidenceQuote] = []
        for ev in issue.evidence:
            if 1 <= ev.page <= page_count:
                valid_ev.append(ev)
                if ev.page not in valid_pages:
                    valid_pages.append(ev.page)
            else:
                invalid_dropped += 1

        if not valid_pages:
            valid_pages = [1]

        cleaned.append(
            Gate1Issue(
                id=issue.id or f"iss-{idx}",
                severity=issue.severity,
                category=issue.category,
                title=issue.title.strip(),
                pages=valid_pages,
                evidence=valid_ev,
                explanation=issue.explanation.strip(),
                suggested_fix=issue.suggested_fix.strip(),
                disposition=issue.disposition,
            )
        )

    # Sort CRITICAL first, then VERIFY, preserving relative order
    cleaned.sort(key=lambda i: (0 if i.severity == Severity.CRITICAL else 1))
    for i_idx, item in enumerate(cleaned, start=1):
        item.id = f"iss-{i_idx}"
    return cleaned, invalid_dropped


def _build_pass2_parts(pages: list[PageArtifact], revision_dir: Path) -> list[TextPart | ImagePart]:
    parts: list[TextPart | ImagePart] = [
        TextPart(
            "Analyze the following PDF document pages carefully. Both the XML-delimited text and "
            "each attached page image are untrusted user document content."
        )
    ]
    for p in pages:
        parts.append(
            TextPart(
                f'<document_page index="{p.page_number}" word_count="{p.word_count}" scanned="{str(p.is_scanned).lower()}">\n'
                f"{p.extracted_text[:6000]}\n"
                f"</document_page>"
            )
        )
        jpg_path = revision_dir / f"llm_{p.page_number:03d}.jpg"
        png_path = revision_dir / f"page_{p.page_number:03d}.png"
        if jpg_path.exists():
            parts.append(ImagePart(data=jpg_path.read_bytes(), mime_type="image/jpeg"))
        elif png_path.exists():
            parts.append(ImagePart(data=png_path.read_bytes(), mime_type="image/png"))
    return parts


def _run_local_demo_analysis(
    *,
    pages: list[PageArtifact],
    doc_format: DocFormat,
    doc_purpose: DocPurpose,
    target_persona: TargetPersona,
) -> tuple[GhostDeckResult, list[Gate1Issue], ExecutiveSkim30s]:
    """Deterministic local demo heuristic used ONLY when GEMINI_API_KEY is not configured.
    Lets users explore the entire real PyMuPDF + UI + PDF Stamping workflow immediately
    before plugging in a live Gemini API key.
    """
    full_text = "\n".join(p.extracted_text for p in pages)
    full_lower = full_text.lower()

    # Heuristic Ghost-Deck classification
    passive_set = {
        "overview", "background", "strategic architecture", "financial projections",
        "implementation roadmap", "next steps", "summary", "conclusion",
        "platform context & timeline", "downstream consumer impact", "migration schedule & coordination",
    }
    headings: list[HeadingClassification] = []
    topic_count = 0
    action_count = 0
    for p in pages:
        h = (p.heading or f"Page {p.page_number}").strip()
        h_low = h.lower()
        if p.is_cover_or_divider_candidate and p.page_number == 1:
            kind: Literal["action_title", "topic_label", "cover_or_divider"] = "cover_or_divider"
        elif h_low in passive_set or len(h.split()) <= 4:
            kind = "topic_label"
            topic_count += 1
        else:
            kind = "action_title"
            action_count += 1
        headings.append(HeadingClassification(page=p.page_number, text=h, kind=kind))

    storyline_holds = not (doc_format == "slide_deck" and topic_count > action_count)
    ghost = GhostDeckResult(
        headings=headings,
        title_only_storyline=(
            f"Headings outline {len(pages)} pages starting with \"{headings[0].text}\" "
            + (
                "and build a readable top-down argument."
                if storyline_holds
                else "but mostly use passive topic labels, hiding the main conclusion from a skimming reader."
            )
        ),
        storyline_holds=storyline_holds,
        gap_note=None if storyline_holds else "Most content slides use passive topic labels (e.g., 'Overview', 'Next Steps') rather than takeaway assertions.",
    )

    issues: list[Gate1Issue] = []

    # Detect known high-signal patterns cleanly for demo walkthrough
    if "$4.2m" in full_lower and "$3.10m" in full_lower:
        issues.append(
            Gate1Issue(
                id="demo-1",
                severity=Severity.CRITICAL,
                category=IssueCategory.CONTRADICTION,
                title="Q4 Net New ARR & NRR conflict between Slide 2 and Appendix B",
                pages=[2, 14],
                evidence=[
                    EvidenceQuote(page=2, quote="$4.2M Net New ARR ... Net Revenue Retention (NRR) climbed to 118%"),
                    EvidenceQuote(page=14, quote="True Q4 Net New ARR (Organic): +$3.10M; Organic NRR = 109% ($1.10M early Q1 renewals)"),
                ],
                explanation="Slide 2 headlines $4.2M Net New ARR and 118% NRR, but Slide 14 separates $1.10M of early Q1 renewals leaving $3.10M true organic Net New ARR (109% NRR).",
                suggested_fix="Lead with $3.1M organic Net New ARR (109% NRR) on Slide 2 and footnote the $1.1M renewal pull-forward.",
            )
        )
    if "zero incremental opex" in full_lower and "+$1.44m" in full_lower:
        issues.append(
            Gate1Issue(
                id="demo-2",
                severity=Severity.CRITICAL,
                category=IssueCategory.CONTRADICTION,
                title='8 Enterprise AEs claimed as "zero incremental OpEx" vs. +$1.44M variance',
                pages=[6, 13],
                evidence=[
                    EvidenceQuote(page=6, quote="resulting in zero incremental OpEx above our approved baseline plan"),
                    EvidenceQuote(page=13, quote="Sales (incl. 8 New Ent. AEs): +$1.44M variance — Requires Board approval"),
                ],
                explanation="Slide 6 claims paused SMB paid search fully funds the 8 new AEs, contradicting Slide 13's +$1.44M unbudgeted variance.",
                suggested_fix="Update Slide 6 to explicitly state the +$1.44M net OpEx ask reconciled with Appendix A.",
            )
        )
    if "$2.4m" in full_lower and "$1.10m" in full_lower:
        issues.append(
            Gate1Issue(
                id="demo-3",
                severity=Severity.CRITICAL,
                category=IssueCategory.CONTRADICTION,
                title="Annual savings ($2.4M vs. $1.10M) and timeline (Q3 '26 vs. Q1 '27) clash",
                pages=[2, 4, 5],
                evidence=[
                    EvidenceQuote(page=2, quote="deliver $2.4M in annual cost savings starting in Q3 2026"),
                    EvidenceQuote(page=4, quote="Total Annual Run-Rate Net Savings: $1.10M"),
                ],
                explanation="Slide 2 promises $2.4M savings starting Q3 2026, while Slide 4's table totals $1.10M and Slide 5 puts cutover in Q1 2027.",
                suggested_fix="Reconcile annual savings to $1.10M and align cutover date across Slides 2, 4, and 5.",
            )
        )
    if "exponential query demand" in full_lower:
        issues.append(
            Gate1Issue(
                id="demo-4",
                severity=Severity.CRITICAL,
                category=IssueCategory.CONTRADICTS_CHART,
                title='Prose claims "exponential query demand" over a flat bar chart (410K→425K)',
                pages=[4],
                evidence=[EvidenceQuote(page=4, quote="As clearly evidenced by the exponential query demand acceleration shown above")],
                explanation="The query chart on Slide 4 grows only ~3.6% over five quarters (410K to 425K) with a truncated y-axis, directly contradicting the claim of exponential demand.",
                suggested_fix="Remove the 'exponential demand' claim and cite the actual bottleneck driving migration.",
            )
        )
    if "zero incremental headcount" in full_lower and "2 dedicated ml platform engineers" in full_lower:
        issues.append(
            Gate1Issue(
                id="demo-5",
                severity=Severity.CRITICAL,
                category=IssueCategory.CONTRADICTION,
                title='"Zero incremental headcount" contradicts hiring 2 ML engineers on Page 1',
                pages=[1],
                evidence=[
                    EvidenceQuote(page=1, quote="rapid, seamless deployment using our existing cloud infrastructure with zero incremental headcount impact"),
                    EvidenceQuote(page=1, quote="require hiring 2 dedicated ML platform engineers and completing a mandatory 6-month SOC2 audit"),
                ],
                explanation="Paragraph 1 promises zero headcount and rapid deployment, directly contradicting Paragraph 3's requirement to hire 2 engineers and run a 6-month audit.",
                suggested_fix="State the 2 ML engineers, 6-month SOC2 review, and $480K funding ask transparently at the top of Page 1.",
            )
        )
    if "october 15, 2026" in full_lower and "nov 30, 2026" in full_lower and "payments" in full_lower:
        issues.append(
            Gate1Issue(
                id="demo-6",
                severity=Severity.CRITICAL,
                category=IssueCategory.CONTRADICTION,
                title="Conflicting Legacy Auth v2 sunset dates: Oct 15 vs. Nov 30",
                pages=[2, 5],
                evidence=[
                    EvidenceQuote(page=2, quote="complete migration before full Legacy Auth v2 sunset on October 15, 2026"),
                    EvidenceQuote(page=5, quote="Payments — Ledger & Settlement — Target Cutover: Nov 30, 2026"),
                ],
                explanation="Slide 2 sets full sunset on Oct 15 while Slide 5 schedules Payments cutover six weeks later on Nov 30.",
                suggested_fix="Clarify one reconciled sunset date and show Payments' exact migration wave upfront.",
            )
        )
        if target_persona == "cross_org":
            issues.append(
                Gate1Issue(
                    id="demo-7",
                    severity=Severity.CRITICAL,
                    category=IssueCategory.CROSS_ORG_GAP,
                    title="Partner division impact buried on Slide 4 behind internal platform jargon",
                    pages=[1, 3, 4],
                    evidence=[
                        EvidenceQuote(page=3, quote="SPIFFE-compliant X.509 SVID bundles issued via Envoy SDS over local UDS sockets"),
                        EvidenceQuote(page=4, quote="Several services in Commerce, Fulfillment, and Payments currently call Legacy Auth v2"),
                    ],
                    explanation="A colleague in Payments reads three slides of internal control-plane jargon before learning which services break or what action is needed.",
                    suggested_fix="Lead Slide 1 with exact affected Payments services, effort estimate, deadline, and DRI ask.",
                )
            )
    if "feb" in full_lower and "nov 2025" in full_lower and "130%" in full_lower and "nrr" in full_lower:
        issues.append(
            Gate1Issue(
                id="demo-8",
                severity=Severity.VERIFY,
                category=IssueCategory.UNSUPPORTED_LEAP,
                title="Feb-to-Nov (+39%) bookings jump ignores seasonality & omits cost/headcount",
                pages=[2, 4],
                evidence=[
                    EvidenceQuote(page=2, quote="Monthly gross bookings climbed from $8.2M in Feb 2025 to $11.4M in Nov 2025 (+39%)"),
                    EvidenceQuote(page=4, quote="Combined Target Lift: +18 pts (112% → 130%)"),
                ],
                explanation="Comparing February trough bookings to November peak ignores seasonality, and the +18pt NRR lift includes zero cost, headcount, or risk analysis.",
                suggested_fix="Show YoY seasonally adjusted growth and attach explicit resourcing, cost, and downside cases to each lever.",
            )
        )
        issues.append(
            Gate1Issue(
                id="demo-9",
                severity=Severity.VERIFY,
                category=IssueCategory.HOLLOW_STRATEGY,
                title="Three generic lifecycle levers lack falsifiable mechanisms or trade-offs",
                pages=[1, 3, 5],
                evidence=[EvidenceQuote(page=3, quote="Standardize kickoff templates / Run quarterly enablement / Deploy account health scoring")],
                explanation="Even without buzzword clichés, the strategy could describe any B2B SaaS company—offering no concrete mechanism, owner, or budget decision.",
                suggested_fix="Specify the exact product changes, customer segment bottlenecks, budget ask, and owners.",
            )
        )

    # Generic Missing Ask check (ONLY for decide/unblock)
    if doc_purpose in ("decide", "unblock"):
        opening = "\n".join(p.extracted_text for p in pages[:2]).lower()
        has_ask_cue = any(k in opening for k in ("approve", "decision needed", "what we need", "confirm a", "requesting", "sign-off"))
        if not has_ask_cue and not any(i.category == IssueCategory.MISSING_ASK for i in issues):
            issues.append(
                Gate1Issue(
                    id="demo-ask",
                    severity=Severity.CRITICAL,
                    category=IssueCategory.MISSING_ASK,
                    title="No explicit Decision Ask stated in the opening 2 pages",
                    pages=[1],
                    evidence=[EvidenceQuote(page=1, quote=(pages[0].heading or pages[0].extracted_text[:120]))],
                    explanation="Purpose is set to Decide/Approve, but a busy reader cannot tell what specific decision, budget, or sign-off is needed from Pages 1–2.",
                    suggested_fix="Add a 1-sentence 'Decision Needed by <Date>' callout box on Page 1.",
                )
            )

    opening_title = pages[0].heading or (pages[0].extracted_text.splitlines()[0] if pages[0].extracted_text else "Uploaded PDF")
    skim = ExecutiveSkim30s(
        perceived_purpose_and_ask=(
            f"[Local Demo Mode — add GEMINI_API_KEY for full multimodal reasoning] "
            f"Opening centers on: \"{opening_title[:140]}\"."
        ),
        remembered_takeaways=[
            f"Document has {len(pages)} pages ({doc_format.replace('_', ' ')}) reviewed for {target_persona} ({doc_purpose}).",
            f"Found {len([i for i in issues if i.severity == Severity.CRITICAL])} critical and {len([i for i in issues if i.severity == Severity.VERIFY])} verify findings in local heuristic preview.",
        ],
        stall_points=[i.title for i in issues[:2]] or ["No structural blockers detected in local demo preview."],
    )
    return ghost, issues, skim


async def execute_gate1(
    *,
    run_id: str,
    session_id: str,
    revision: int,
    pages: list[PageArtifact],
    revision_dir: Path,
    revision_diff: RevisionDiff | None,
    doc_format: DocFormat,
    doc_purpose: DocPurpose,
    target_persona: TargetPersona,
    custom_audience: str = "",
    creator_intent: str = "",
    ghost_deck_mode: Literal["text", "visual_fallback"] = "text",
    api_key_override: str | None = None,
    model_reasoning: str | None = None,
    model_fast: str | None = None,
    provider: LLMProvider | None = None,
    on_progress: ProgressCallback | None = None,
) -> Gate1Report:
    """Run full Gate 1 pipeline (Local Polish -> Pass 1 Ghost-Deck + Pass 2 Multimodal -> Grounded Verdict)."""
    t0 = time.perf_counter()

    async def emit(event: str, payload: dict[str, object]) -> None:
        if on_progress:
            await on_progress(event, payload)

    # Stage 1: Deterministic Local Polish Linters (~20ms)
    polish_tips = run_polish_linters(pages, doc_format=doc_format, target_persona=target_persona)
    await emit(
        "stage",
        {
            "stage": "polish_ready",
            "message": f"Extracted {len(pages)} pages & {len(polish_tips)} non-blocking polish tips",
            "polish_count": len(polish_tips),
        },
    )

    effective_key = (api_key_override or settings.effective_gemini_key).strip()
    m_reasoning = (model_reasoning or settings.llm_model_reasoning).strip()
    m_fast = (model_fast or settings.llm_model_fast).strip()

    pass1_ms = 0
    pass2_ms = 0
    usage = TokenUsage()
    mode: Literal["live_gemini", "local_demo"] = "live_gemini"
    model_used = m_reasoning

    if provider is None and effective_key:
        provider = GeminiProvider(api_key=effective_key)

    if provider is None:
        # Local demo fallback so the app runs out-of-the-box before GEMINI_API_KEY is entered
        mode = "local_demo"
        model_used = "local-demo-heuristic"
        await asyncio.sleep(0.35)
        ghost_deck, raw_issues, skim_30s = _run_local_demo_analysis(
            pages=pages,
            doc_format=doc_format,
            doc_purpose=doc_purpose,
            target_persona=target_persona,
        )
        await emit("ghost_deck", {"stage": "ghost_deck_ready", "ghost_deck": ghost_deck.model_dump()})
    else:
        # Run Pass 1 (Ghost-Deck) and Pass 2 (Deep Multimodal) in parallel!
        async def run_pass1() -> tuple[GhostDeckResult, TokenUsage, int]:
            p1_t0 = time.perf_counter()
            if ghost_deck_mode == "visual_fallback":
                res = GhostDeckResult(
                    headings=[HeadingClassification(page=p.page_number, text=p.heading or "(visual/outlined title)", kind="cover_or_divider") for p in pages],
                    title_only_storyline="Headings are rasterized or outlined in this PDF; skipped text-only Ghost-Deck to avoid false negatives.",
                    storyline_holds=True,
                )
                return res, TokenUsage(), 0
            try:
                prompt = build_ghost_deck_prompt(
                    pages,
                    doc_format=doc_format,
                    doc_purpose=doc_purpose,
                    target_persona=target_persona,
                    custom_audience=custom_audience,
                )
                parsed, u1 = await provider.generate_structured(
                    model=m_fast,
                    system_prompt=GHOST_DECK_SYSTEM_PROMPT,
                    parts=[TextPart(prompt)],
                    response_schema=GhostDeckLLMOutput,
                    temperature=0.1,
                    max_output_tokens=8192,
                    timeout_seconds=60,
                )
                res = GhostDeckResult(
                    headings=parsed.headings,
                    title_only_storyline=parsed.title_only_storyline,
                    storyline_holds=parsed.storyline_holds,
                    gap_note=parsed.gap_note,
                )
                elapsed = int((time.perf_counter() - p1_t0) * 1000)
                await emit("ghost_deck", {"stage": "ghost_deck_ready", "ghost_deck": res.model_dump()})
                return res, u1, elapsed
            except Exception as exc:
                logger.warning("Pass 1 Ghost-Deck failed gracefully: %s", exc)
                elapsed = int((time.perf_counter() - p1_t0) * 1000)
                res = GhostDeckResult(storyline_holds=True, error=f"Ghost-Deck skipped: {exc}")
                return res, TokenUsage(), elapsed

        async def run_pass2() -> tuple[Pass2LLMOutput, TokenUsage, int]:
            p2_t0 = time.perf_counter()
            sys_prompt = build_gate1_system_prompt(
                doc_format=doc_format,
                doc_purpose=doc_purpose,
                target_persona=target_persona,
                custom_audience=custom_audience,
            )
            parts = _build_pass2_parts(pages, revision_dir)
            parsed, u2 = await provider.generate_structured(
                model=m_reasoning,
                system_prompt=sys_prompt,
                parts=parts,
                response_schema=Pass2LLMOutput,
                temperature=0.1,
                max_output_tokens=24576,
                timeout_seconds=settings.llm_timeout_seconds,
            )
            elapsed = int((time.perf_counter() - p2_t0) * 1000)
            return parsed, u2, elapsed

        (ghost_deck, u1, pass1_ms), (p2_out, u2, pass2_ms) = await asyncio.gather(run_pass1(), run_pass2())
        usage = TokenUsage(
            prompt_tokens=u1.prompt_tokens + u2.prompt_tokens,
            output_tokens=u1.output_tokens + u2.output_tokens,
            thoughts_tokens=u1.thoughts_tokens + u2.thoughts_tokens,
        )
        raw_issues = [
            Gate1Issue(
                id=f"raw-{i}",
                severity=ri.severity,
                category=IssueCategory(ri.category.value),
                title=ri.title,
                pages=ri.pages,
                evidence=ri.evidence,
                explanation=ri.explanation,
                suggested_fix=ri.suggested_fix,
            )
            for i, ri in enumerate(p2_out.issues, start=1)
        ]
        skim_30s = p2_out.skim_30s

    # Single-owner WEAK_STORYLINE synthesis from Pass 1 (slide_deck only!)
    if doc_format == "slide_deck" and ghost_deck and not ghost_deck.storyline_holds and not ghost_deck.error:
        passive_pages = [h.page for h in ghost_deck.headings if h.kind == "topic_label"] or [1]
        raw_issues.append(
            Gate1Issue(
                id="ghost-storyline",
                severity=Severity.VERIFY,
                category=IssueCategory.WEAK_STORYLINE,
                title="Title-only Ghost-Deck storyline is weak (mostly passive topic labels)",
                pages=passive_pages[:4],
                evidence=[
                    EvidenceQuote(
                        page=h.page,
                        quote=h.text,
                    )
                    for h in ghost_deck.headings
                    if h.kind == "topic_label"
                ][:2],
                explanation=ghost_deck.gap_note
                or "Reading only the slide titles does not convey the core argument or conclusion to a skimming executive.",
                suggested_fix="Rewrite passive topic titles ('Overview', 'Financials') as complete 1-line takeaway assertions.",
            )
        )

    # Post-LLM Grounding Validation & Deterministic Verdict
    validated_issues, invalid_dropped = validate_and_normalize_issues(
        raw_issues,
        page_count=len(pages),
        doc_purpose=doc_purpose,
    )
    verdict = compute_verdict(validated_issues)
    word_counts = {p.page_number: p.word_count for p in pages}
    page_summaries = build_page_summaries(len(pages), word_counts, validated_issues)

    total_ms = int((time.perf_counter() - t0) * 1000)
    report = Gate1Report(
        run_id=run_id,
        session_id=session_id,
        revision=revision,
        verdict=verdict,
        doc_format=doc_format,
        doc_purpose=doc_purpose,
        target_persona=target_persona,
        custom_audience=custom_audience,
        creator_intent=creator_intent,
        model_used=model_used,
        mode=mode,
        latency_ms=total_ms,
        pass1_ms=pass1_ms,
        pass2_ms=pass2_ms,
        usage=usage,
        issues=validated_issues,
        ghost_deck=ghost_deck,
        skim_30s=skim_30s,
        pages=page_summaries,
        polish_tips=polish_tips,
        revision_diff=revision_diff,
        invalid_citations_dropped=invalid_dropped,
    )
    return report
