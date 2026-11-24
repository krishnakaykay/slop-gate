"""Fast deterministic Polish linters (strictly non-blocking).

Implements Amazon clear-writing heuristics (unquantified weasel words/adjectives,
wordy fluff, >30-word sentences on memos, unexpanded local acronyms) and slide
text-bandwidth hints without ever triggering false-positive pass/fail blocks.
"""

from __future__ import annotations

import re

from app.schemas.document import DocFormat, PageArtifact, TargetPersona
from app.schemas.gate1 import PolishTip

WEASEL_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(significantly|substantially|dramatically|massively|vastly|exponentially)\b", re.I),
     "Replace intensifier with a before/after metric and baseline (Amazon data-over-adjectives rule)."),
    (re.compile(r"\b(nearly all|almost all|many customers|several stakeholders|virtually zero)\b", re.I),
     "Replace vague quantifier with an exact count or percentage."),
    (re.compile(r"\b(world-class|best-in-class|synergistic|holistic|paradigm shift|seamlessly|seamless)\b", re.I),
     "Cut generic buzzword and name the concrete operational mechanism instead."),
    (re.compile(r"\b(due to the fact that|in order to|has the ability to|at this point in time)\b", re.I),
     "Trim wordy corporate phrasing (e.g., 'due to the fact that' -> 'because')."),
]

# Standard executive / engineering acronyms that should NOT nag Leadership persona
STANDARD_LEADERSHIP_ACRONYMS = {
    "AI", "ML", "UI", "UX", "API", "SDK", "SQL", "AWS", "GCP", "KPI", "ROI", "ARR", "MRR",
    "NRR", "CAC", "LTV", "SLA", "SLO", "PII", "QA", "Q1", "Q2", "Q3", "Q4", "H1", "H2",
    "FY", "YOY", "CEO", "CFO", "CTO", "CRO", "VP", "PM", "EM", "HR", "IT", "US", "UK",
    "EU", "USD", "EUR", "GBP", "PDF", "FAQ", "PR", "DRI", "OKR", "B2B", "B2C", "SMB",
    "EMEA", "APAC", "AMER", "DACH", "TAM", "SAM", "SOM", "CRM", "ERP", "BI", "CI", "CD",
    "RPC", "TLS", "HTTP", "HTTPS", "URL", "JSON", "YAML", "CPU", "GPU", "RAM", "NVME",
    "IOPS", "TPS", "RTT", "WAL", "LSM", "CRC", "EC2", "S3", "UTC", "SRE", "SEV", "RFC",
    "SSO", "SOC2", "SOC", "GDPR", "HIPAA", "PCI", "ACV", "FTE", "OTE", "CSM", "AE",
    "OPEX", "CAPEX", "TCO", "GMV", "FY25", "FY26", "FY27", "CY26", "CY27", "ID", "II",
    "III", "IV", "VS", "EG", "IE", "NA", "TBD", "ETC", "P0", "P1", "P2",
}

ACRONYM_RE = re.compile(r"\b([A-Z]{2,6})\b")
DIGIT_RE = re.compile(r"\d")


def _split_sentences(text: str) -> list[str]:
    clean = re.sub(r"\s+", " ", text).strip()
    if not clean:
        return []
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", clean) if s.strip()]


def _is_expanded_anywhere(full_doc_text: str, acronym: str) -> bool:
    # Matches "... (ACR)" or "ACR ("
    return bool(re.search(rf"\({re.escape(acronym)}\)|\b{re.escape(acronym)}\s*\(", full_doc_text))


def run_polish_linters(
    pages: list[PageArtifact],
    *,
    doc_format: DocFormat,
    target_persona: TargetPersona,
) -> list[PolishTip]:
    tips: list[PolishTip] = []
    full_doc_text = "\n".join(p.extracted_text for p in pages)
    seen_acronyms: set[str] = set()

    for page in pages:
        if page.is_scanned or not page.extracted_text:
            continue

        # 1. Weasel words & unquantified adjectives (skip if sentence already contains hard numbers)
        weasel_hits_on_page = 0
        for sent in _split_sentences(page.extracted_text):
            if weasel_hits_on_page >= 2:
                break
            has_number = bool(DIGIT_RE.search(sent))
            for pat, suggestion in WEASEL_PATTERNS:
                m = pat.search(sent)
                if not m:
                    continue
                # Allow intensifiers if grounded with hard numbers in the same sentence,
                # EXCEPT always flag pure corporate fluff/buzzwords
                is_pure_fluff = pat.pattern.startswith(r"\b(world-class") or pat.pattern.startswith(r"\b(due to")
                if has_number and not is_pure_fluff:
                    continue
                tips.append(
                    PolishTip(
                        page=page.page_number,
                        kind="weasel_word",
                        snippet=f'"{m.group(0)}"',
                        suggestion=suggestion,
                    )
                )
                weasel_hits_on_page += 1
                break

        # 2. Long sentences (>30 words) on Narrative Memos
        if doc_format == "narrative_memo":
            long_on_page = 0
            for sent in _split_sentences(page.extracted_text):
                if long_on_page >= 2:
                    break
                # Skip heading-like lines or bullet fragments
                if len(sent) > 20 and not sent.startswith(("•", "-", "*")):
                    wc = len(sent.split())
                    if wc > 32:
                        excerpt = " ".join(sent.split()[:10]) + "…"
                        tips.append(
                            PolishTip(
                                page=page.page_number,
                                kind="long_sentence",
                                snippet=f"{wc} words: {excerpt}",
                                suggestion="Amazon clear-writing rule: split sentences over ~30 words into two crisp thoughts.",
                            )
                        )
                        long_on_page += 1

        # 3. Dense slide word-count hint (Slide Decks only)
        if doc_format == "slide_deck" and page.word_count > 135:
            tips.append(
                PolishTip(
                    page=page.page_number,
                    kind="dense_slide",
                    snippet=f"{page.word_count} words on Slide {page.page_number}",
                    suggestion="Slide exceeds comfortable scanning bandwidth (~100–120 words); trim bullets or move detail to appendix.",
                )
            )

        # 4. Unexpanded acronyms (persona-aware to honor Reverse Cohesion Effect)
        for m in ACRONYM_RE.finditer(page.extracted_text):
            acr = m.group(1)
            if acr in seen_acronyms:
                continue
            if target_persona == "leadership" and acr in STANDARD_LEADERSHIP_ACRONYMS:
                continue
            # Even for cross-org, skip tiny ubiquitous tokens like US/UK/EU/Q1..Q4/PDF/AI
            if acr in {"US", "UK", "EU", "Q1", "Q2", "Q3", "Q4", "H1", "H2", "PDF", "AI", "ID", "VS", "USD", "EUR", "GBP", "PR", "FAQ", "UTC"}:
                continue
            if not _is_expanded_anywhere(full_doc_text, acr):
                seen_acronyms.add(acr)
                tips.append(
                    PolishTip(
                        page=page.page_number,
                        kind="unexpanded_acronym",
                        snippet=acr,
                        suggestion=(
                            f"Spell out '{acr}' on first use for readers outside your division."
                            if target_persona == "cross_org"
                            else f"Project/local acronym '{acr}' appears without first-use expansion."
                        ),
                    )
                )

    # Cap total polish tips so the drawer stays clean and scannable
    return tips[:24]
