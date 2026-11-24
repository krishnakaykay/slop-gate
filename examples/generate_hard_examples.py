#!/usr/bin/env python3
"""
Generate 4 hard / middle-ground calibration PDFs for Slop Gate (Gate 1):
  1. examples/hard/01_hard_smooth_2026_ai_slop.pdf
     - Hard Negative: Zero buzzword cliches, clean layout, crisp chart,
       but cherry-picked seasonal baseline, hollow strategy, zero real trade-offs/costs.
  2. examples/hard/02_hard_messy_human_genius_rfc.pdf
     - False-Positive Trap (MUST PASS / READY): Dense plain Principal Engineer RFC
       with passive headings & unexpanded domain acronyms (p99, WAL, gRPC, LSM),
       but airtight math, real benchmarks, explicit Ask, and sharp trade-offs.
  3. examples/hard/03_hard_inform_only_sev1_postmortem.pdf
     - Purpose = Inform/Align (MUST PASS / READY): Crisp SEV-1 postmortem with
       no funding/approval Ask — ensures Inform-only docs aren't penalized for missing Ask.
  4. examples/hard/04_hard_15p_exec_deck_appendix_contradiction.pdf
     - Long-Context Subtle Contradiction Test (MUST FLAG CRITICAL): 15-slide mostly sharp
       exec QBR/FY27 plan with 2 subtle contradictions buried between Slides 2 & 14
       ($4.2M / 118% NRR vs. $3.1M / 109% NRR) and Slides 6 & 13 (zero incremental OpEx vs. +$1.44M variance).
"""

import io
import os
import tempfile

os.environ.setdefault("MPLCONFIGDIR", tempfile.mkdtemp(prefix="mpl_hard_"))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    HRFlowable,
)
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HARD_DIR = os.path.join(BASE_DIR, "hard")
os.makedirs(HARD_DIR, exist_ok=True)

SLIDE_W, SLIDE_H = 13.333 * inch, 7.5 * inch


def fig_to_buf(fig, dpi=160):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf


def draw_wrapped(c, text, x, y, max_w, font_name="Helvetica", font_size=12, leading=16, color=colors.black):
    style = ParagraphStyle("tmp", fontName=font_name, fontSize=font_size, leading=leading, textColor=color)
    p = Paragraph(text, style)
    _, h = p.wrap(max_w, 1000)
    p.drawOn(c, x, y - h)
    return y - h


# =============================================================================
# HARD CASE 1: "SMOOTH 2026 AI SLOP" (Clean aesthetic, zero cliches, hollow core)
# =============================================================================

def chart_cherry_picked_growth():
    """Clean modern chart that hides seasonality by comparing Feb trough to Nov Black Friday peak."""
    fig, ax = plt.subplots(figsize=(6.0, 3.2), facecolor="white")
    months = ["Feb '25", "Apr '25", "Jul '25", "Sep '25", "Nov '25"]
    rev = [8.2, 8.7, 9.1, 9.5, 11.4]
    bars = ax.bar(months, rev, width=0.52, color=["#CBD5E1", "#CBD5E1", "#CBD5E1", "#CBD5E1", "#1E293B"])
    for b, v in zip(bars, rev):
        ax.text(b.get_x() + b.get_width() / 2, v + 0.25, f"\\${v:.1f}M", ha="center", fontsize=9, fontweight="bold", color="#0F172A")
    ax.set_ylim(0, 13.2)
    ax.set_ylabel("Monthly Gross Bookings ($M)", fontsize=9)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", color="#F1F5F9")
    ax.set_title("Selected Monthly Enterprise Bookings (Feb vs. Nov 2025)", fontsize=9.5, fontweight="bold", loc="left", pad=8)
    return fig_to_buf(fig)


def build_hard_smooth_2026_slop():
    """Zero cliche buzzwords, crisp typography, action-ish titles, clean chart —
    yet hollow strategy, cherry-picked seasonal baseline, missing costs/headcount, zero real trade-offs."""
    path = os.path.join(HARD_DIR, "01_hard_smooth_2026_ai_slop.pdf")
    c = canvas.Canvas(path, pagesize=(SLIDE_W, SLIDE_H))

    def hdr(kicker, title, num):
        c.setFillColor(colors.HexColor("#475569"))
        c.setFont("Helvetica-Bold", 9)
        c.drawString(0.75 * inch, SLIDE_H - 0.52 * inch, kicker.upper())
        draw_wrapped(c, title, 0.75 * inch, SLIDE_H - 0.68 * inch, SLIDE_W - 1.5 * inch,
                     "Helvetica-Bold", 19.5, 24, colors.HexColor("#0F172A"))
        c.setStrokeColor(colors.HexColor("#E2E8F0"))
        c.line(0.75 * inch, SLIDE_H - 1.38 * inch, SLIDE_W - 0.75 * inch, SLIDE_H - 1.38 * inch)
        c.setFillColor(colors.HexColor("#94A3B8"))
        c.setFont("Helvetica", 8.5)
        c.drawString(0.75 * inch, 0.35 * inch, "FY27 Enterprise Expansion Strategy | Draft for Leadership Review")
        c.drawRightString(SLIDE_W - 0.75 * inch, 0.35 * inch, f"{num} / 5")

    # Slide 1: Looks crisp, actually says nothing falsifiable (no Ask, no cost, generic 3 pillars)
    hdr("Executive Summary", "Accelerating enterprise expansion can lift net retention to 130% across FY27.", 1)
    cards = [
        ("1. Sharper Onboarding", "Reduce friction during the first 90 days",
         "Streamline implementation workflows, tailor playbooks by segment, and align Customer Success touchpoints around early value milestones."),
        ("2. Self-Serve Expansion", "Unlock organic seat and usage growth",
         "Introduce clearer in-product upgrade paths, flexible usage tiers, and proactive adoption nudges for teams approaching plan limits."),
        ("3. Disciplined Renewals", "Protect base retention ahead of renewal dates",
         "Start executive business reviews earlier, surface health signals to account teams, and standardize multi-year commercial offers."),
    ]
    for i, (h, sub, body) in enumerate(cards):
        x = 0.75 * inch + i * 4.05 * inch
        c.setFillColor(colors.HexColor("#F8FAFC"))
        c.setStrokeColor(colors.HexColor("#E2E8F0"))
        c.roundRect(x, 1.55 * inch, 3.75 * inch, 4.0 * inch, 6, fill=1, stroke=1)
        draw_wrapped(c, h, x + 0.24 * inch, 5.25 * inch, 3.25 * inch, "Helvetica-Bold", 12, 16, colors.HexColor("#0F172A"))
        draw_wrapped(c, sub, x + 0.24 * inch, 4.88 * inch, 3.25 * inch, "Helvetica-Bold", 10.5, 14, colors.HexColor("#334155"))
        draw_wrapped(c, body, x + 0.24 * inch, 4.32 * inch, 3.25 * inch, "Helvetica", 10.8, 15.5, colors.HexColor("#475569"))
    c.showPage()

    # Slide 2: Cherry-picked seasonal baseline (Feb trough vs Nov peak = "39% structural momentum"!)
    hdr("Commercial Momentum", "Enterprise bookings rose 39% from Feb to Nov 2025, confirming strong expansion demand.", 2)
    ch_buf = chart_cherry_picked_growth()
    c.drawImage(ImageReader(ch_buf), 0.75 * inch, 1.8 * inch, width=6.7 * inch, height=3.8 * inch, preserveAspectRatio=True)
    draw_wrapped(
        c,
        "<b>Key Observations:</b><br/><br/>"
        "• Monthly gross bookings climbed from $8.2M in Feb 2025 to $11.4M in Nov 2025 (+39%).<br/><br/>"
        "• Account teams report strong appetite for multi-team deployments when executive sponsorship is present.<br/><br/>"
        "• Maintaining this trajectory puts our 130% Net Revenue Retention target well within reach across FY27.",
        7.85 * inch, 5.3 * inch, 4.7 * inch, font_size=11.5, leading=16.5, color=colors.HexColor("#334155")
    )
    c.showPage()

    # Slide 3: Smooth generic playbook — could belong to ANY B2B SaaS company on earth
    hdr("Operating Levers", "Three coordinated initiatives improve customer lifecycle conversion end to end.", 3)
    tbl = Table([
        ["Lifecycle Stage", "Current Gap", "Planned Approach", "Target Outcome"],
        ["Onboarding", "Inconsistent time-to-value\nacross account sizes", "Standardize kickoff templates\nand milestone tracking", "Faster activation and\nhigher early adoption"],
        ["Mid-Term Adoption", "Under-utilized advanced\nproduct modules", "Run quarterly enablement\nand usage check-ins", "Broader seat penetration\nwithin existing accounts"],
        ["Renewal", "Late engagement on\nat-risk renewals", "Deploy account health scoring\n120 days before renewal", "Higher logo retention and\nmulti-year lock-in"],
    ], colWidths=[2.1 * inch, 3.1 * inch, 3.5 * inch, 3.1 * inch])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
        ("FONTSIZE", (0, 0), (-1, -1), 10.5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
    ]))
    tbl.wrapOn(c, 12 * inch, 4.5 * inch)
    tbl.drawOn(c, 0.75 * inch, 2.3 * inch)
    c.showPage()

    # Slide 4: Zero cost, zero headcount, zero trade-offs — pure assumption-free upside
    hdr("Expected Impact", "Executing all three levers lifts NRR from 112% today to 130% by Q4 FY27.", 4)
    impact = Table([
        ["Initiative", "Expected NRR Lift", "Primary Function", "Timing"],
        ["Onboarding Playbooks", "+5 pts", "Customer Success", "H1 FY27"],
        ["Self-Serve Expansion Flows", "+8 pts", "Product & Growth", "H1–H2 FY27"],
        ["Proactive Renewal Motion", "+5 pts", "Account Management", "Ongoing FY27"],
        ["Combined Target Lift", "+18 pts (112% → 130%)", "Cross-Functional", "Full Year FY27"],
    ], colWidths=[3.4 * inch, 2.8 * inch, 3.1 * inch, 2.5 * inch])
    impact.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E293B")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#F1F5F9")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ("FONTSIZE", (0, 0), (-1, -1), 11),
        ("TOPPADDING", (0, 0), (-1, -1), 11),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 11),
    ]))
    impact.wrapOn(c, 12 * inch, 4.5 * inch)
    impact.drawOn(c, 0.75 * inch, 2.5 * inch)
    draw_wrapped(
        c,
        "Note: Lift estimates assume steady macro conditions and coordinated execution across Product, Sales, and Customer Success.",
        0.75 * inch, 2.0 * inch, 11.8 * inch, font_size=10, leading=14, color=colors.HexColor("#64748B")
    )
    c.showPage()

    # Slide 5: Smooth non-committal close (no owners, no budget ask, no decision criteria)
    hdr("Next Steps", "Functional leads will refine quarterly milestones and review progress at Q1 planning.", 5)
    draw_wrapped(
        c,
        "•  Confirm alignment on the three expansion pillars across Product, Sales, and Customer Success leadership.<br/><br/>"
        "•  Scope detailed engineering and enablement requirements during upcoming quarterly roadmap reviews.<br/><br/>"
        "•  Establish shared dashboard tracking for onboarding velocity, expansion conversion, and renewal health.<br/><br/>"
        "•  Reconvene in four weeks to review resourcing options and finalize FY27 targets.",
        0.85 * inch, 5.4 * inch, 11.4 * inch, font_size=13.5, leading=20, color=colors.HexColor("#1E293B")
    )
    c.showPage()
    c.save()
    return path


# =============================================================================
# HARD CASE 2: "MESSY HUMAN GENIUS" RFC (False-Positive Trap — MUST PASS!)
# =============================================================================

def build_hard_messy_human_genius_rfc():
    """Dense Principal Engineer RFC: plain ugly formatting, passive headers ('Latency Analysis',
    'Failure Modes'), unexpanded standard eng acronyms (p99, WAL, gRPC, LSM, CRC32), tight tables —
    but airtight math, real benchmarks, explicit Decision Ask, and ruthless trade-offs. MUST PASS."""
    path = os.path.join(HARD_DIR, "02_hard_messy_human_genius_rfc.pdf")
    doc = SimpleDocTemplate(path, pagesize=letter, leftMargin=0.65 * inch, rightMargin=0.65 * inch,
                            topMargin=0.65 * inch, bottomMargin=0.65 * inch)
    styles = getSampleStyleSheet()
    t_s = ParagraphStyle("t", parent=styles["Title"], fontName="Courier-Bold", fontSize=13.5, alignment=TA_LEFT, spaceAfter=4)
    m_s = ParagraphStyle("m", parent=styles["Normal"], fontName="Courier", fontSize=8.5, textColor=colors.HexColor("#333333"), spaceAfter=8)
    h_s = ParagraphStyle("h", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=11, spaceBefore=10, spaceAfter=4)
    b_s = ParagraphStyle("b", parent=styles["BodyText"], fontName="Helvetica", fontSize=9.5, leading=13, spaceAfter=6)

    story = [
        Paragraph("RFC-142: Replace Sync Raft FS-Fsync on Ledger Write Path With Group-Commit WAL", t_s),
        Paragraph("Author: K. Rao (Principal Eng, Storage) | Reviewers: VP Eng, Storage Staff | Decision Needed: May 18, 2026", m_s),
        HRFlowable(width="100%", color=colors.black, thickness=0.8),
        Spacer(1, 6),

        Paragraph("Summary and Ask", h_s),
        Paragraph(
            "<b>Decision Needed by May 18:</b> Approve moving `ledger-core` from per-RPC fsync to a bounded 4ms group-commit WAL "
            "(Option 2 below). No extra headcount or hardware spend is required (2 eng-weeks from Storage team, already in Q2 plan). "
            "Without this change, peak holiday checkout volume (projected 18,500 write TPS in Nov 2026 vs. 11,200 TPS ceiling today) "
            "will saturate NVMe IOPS and push checkout p99 latency past our 250ms SLA by Oct 2026.",
            b_s
        ),

        Paragraph("Latency Analysis", h_s),
        Paragraph(
            "On May 4 load tests (3-node c7i.8xlarge cluster, NVMe RAID-0, 4KB payload, gRPC TLS 1.3), `ledger-core` hit a hard wall at "
            "11,200 write TPS. Flamegraphs show 74% of wall-clock latency sits in serialized `fdatasync()` syscalls inside the Raft log "
            "appender, not CPU (31% util) or network RTT (0.4ms intra-AZ). Every incoming gRPC write currently triggers its own NVMe flush "
            "(~0.085ms mean, 4.2ms p99 under queue depth >64), capping single-shard throughput well below Q4 demand.",
            b_s
        ),
        Table([
            ["Benchmark Config\n(May 4, 10m sustained)", "Max Write\nTPS", "Write\np50", "Write\np99", "Durability Guarantee", "Cost Delta"],
            ["Current (per-RPC fsync)", "11,200", "2.1 ms", "19.4 ms", "Strict linearizable (0 loss)", "$0"],
            ["Option 1: Async WAL\n(flush every 50ms)", "48,000", "0.9 ms", "4.8 ms", "UNACCEPTABLE:\nup to 50ms loss window", "$0"],
            ["Option 2: 4ms Group-Commit\nWAL (Recommended)", "34,500", "4.6 ms", "9.2 ms", "Strict linearizable (0 loss)", "$0"],
            ["Option 3: 4x Horizontal\nSharding", "41,000", "2.4 ms", "21.0 ms", "Strict linearizable (0 loss)", "+$310K/yr\n+ 14 wks"],
        ], colWidths=[2.0 * inch, 0.85 * inch, 0.65 * inch, 0.65 * inch, 2.0 * inch, 1.05 * inch], style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E5E7EB")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, 3), (-1, 3), "Helvetica-Bold"),
            ("BACKGROUND", (0, 3), (-1, 3), colors.HexColor("#F3F4F6")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#9CA3AF")),
            ("FONTSIZE", (0, 0), (-1, -1), 7.8),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ])),
        Spacer(1, 6),

        Paragraph("Why Option 2 Wins Over Options 1 and 3", h_s),
        Paragraph(
            "Option 1 (async WAL) violates financial audit requirements: a power/kernel panic loses up to 50ms of acknowledged ledger writes "
            "(~900 transactions at peak). Option 3 (4x sharding) solves throughput but costs $310K/yr in EC2/NVMe instances, requires 14 "
            "engineer-weeks of cross-shard 2PC rewrite, and misses our Oct 2026 peak freeze. Option 2 preserves exact zero-data-loss "
            "linearizability—gRPC does not return ACK until the shared 4ms batch hits `fdatasync()` on quorum—while tripling throughput "
            "to 34,500 TPS (1.86x headroom over projected 18,500 Nov peak).",
            b_s
        ),

        Paragraph("Failure Modes and Trade-Offs", h_s),
        Paragraph(
            "<b>1. Median latency rises by +2.5ms (2.1ms → 4.6ms):</b> This is the explicit trade-off of waiting up to 4ms to batch writes. "
            "Checkout end-to-end p50 is 145ms, so +2.5ms is invisible to users, while p99 actually improves from 19.4ms to 9.2ms by eliminating "
            "NVMe queue contention. If low-traffic regions (<200 TPS) dislike the 4ms wait, an adaptive flush triggers immediately when queue=1 "
            "and idle >1ms.",
            b_s
        ),
        Paragraph(
            "<b>2. Partial batch CRC32 tear on crash:</b> If power fails mid-write of a 64-entry WAL batch, Raft recovery truncates to the "
            "last valid CRC32 frame boundary and replays un-ACKed entries cleanly. Tested via Jepsen-style SIGKILL + dm-flakey power-cut fault "
            "injection across 500 cycles (0 corrupted entries, 0 lost ACKs).",
            b_s
        ),
        Paragraph(
            "<b>3. LSM compaction I/O spikes:</b> Group-commit reduces WAL IOPS by 12x, leaving NVMe bandwidth headroom for RocksDB L0→L1 "
            "compactions. We still cap compaction write rate at 180 MB/s to protect tail latency.",
            b_s
        ),

        Paragraph("Rollout & Rollback", h_s),
        Paragraph(
            "Controlled via runtime flag `wal_group_commit_ms` (default 0 = current behavior). Canary 5% traffic in us-west-2 (Jun 1–Jun 7), "
            "50% (Jun 8–Jun 14), 100% (Jun 15). Flipping `wal_group_commit_ms=0` reverts instantly without restart or log format migration "
            "because the on-disk WAL record header is unchanged.",
            b_s
        ),
    ]
    doc.build(story)
    return path


# =============================================================================
# HARD CASE 3: INFORM-ONLY SEV-1 POSTMORTEM (Purpose = Inform/Align — MUST PASS!)
# =============================================================================

def build_hard_inform_only_postmortem():
    """Sharp Inform-Only SEV-1 Postmortem with ZERO funding/approval Ask.
    Tests that Gate 1 does NOT falsely flag 'Missing Ask' when Purpose = Inform/Align."""
    path = os.path.join(HARD_DIR, "03_hard_inform_only_sev1_postmortem.pdf")
    doc = SimpleDocTemplate(path, pagesize=letter, leftMargin=0.8 * inch, rightMargin=0.8 * inch,
                            topMargin=0.75 * inch, bottomMargin=0.75 * inch)
    styles = getSampleStyleSheet()
    t_s = ParagraphStyle("t", parent=styles["Title"], fontSize=16, alignment=TA_LEFT, textColor=colors.HexColor("#0F172A"), spaceAfter=4)
    m_s = ParagraphStyle("m", parent=styles["Normal"], fontSize=9, textColor=colors.HexColor("#475569"), spaceAfter=10)
    h_s = ParagraphStyle("h", parent=styles["Heading2"], fontSize=11.5, spaceBefore=12, spaceAfter=5, textColor=colors.HexColor("#991B1B"))
    b_s = ParagraphStyle("b", parent=styles["BodyText"], fontSize=10, leading=14, spaceAfter=7, textColor=colors.HexColor("#1E293B"))
    box_s = ParagraphStyle("box", parent=b_s, backColor=colors.HexColor("#FEF2F2"), borderPadding=8, spaceAfter=10)

    story = [
        Paragraph("SEV-1 Incident Postmortem: Checkout Tax-Service Timeout (INC-2026-0419)", t_s),
        Paragraph("<b>Purpose:</b> Inform & Align (No decision or budget requested) &nbsp;|&nbsp; <b>Owner:</b> Checkout SRE &nbsp;|&nbsp; <b>Date:</b> Apr 22, 2026", m_s),
        HRFlowable(width="100%", color=colors.HexColor("#CBD5E1")),
        Spacer(1, 8),

        Paragraph(
            "<b>Executive Summary:</b> On April 19, 2026 (14:12–14:59 UTC), a misconfigured connection-pool timeout in the Checkout "
            "Tax Service caused <b>18,400 failed customer checkouts over 47 minutes</b> (~$1.12M gross merchandise value delayed; "
            "64% of affected buyers retried and completed purchase within 2 hours, leaving ~$403K estimated net lost GMV). "
            "Rollback restored full service at 14:59 UTC. Three preventative fixes are scheduled and tracked below.",
            box_s
        ),

        Paragraph("1. Root Cause: Connection-Pool Exhaustion Triggered by Tax-Rate Cache Miss Storm", h_s),
        Paragraph(
            "At 14:05 UTC, deploy `tax-svc-v4.18.2` changed the Redis key prefix for state sales-tax tables without pre-warming the cache. "
            "All 100% of checkout tax lookups fell through to the upstream Avalara API simultaneously. Because our HTTP client lacked a "
            "circuit breaker and kept the default 30-second socket timeout, all 400 worker threads saturated within 7 minutes, returning "
            "HTTP 503 errors to Checkout.",
            b_s
        ),

        Paragraph("2. Incident Timeline (All Times UTC, April 19, 2026)", h_s),
        Table([
            ["Time (UTC)", "Event"],
            ["14:05", "`tax-svc-v4.18.2` promoted to 100% prod traffic (canary skipped cache-prefix check)."],
            ["14:12", "Checkout HTTP 503 error rate crosses 2% threshold; PagerDuty pages Checkout SRE on-call."],
            ["14:19", "Error rate peaks at 68% of US checkout attempts; SEV-1 declared in #inc-0419."],
            ["14:38", "Root cause isolated to `tax-svc` thread-pool saturation after Redis cache miss spike (99.4%)."],
            ["14:46", "Rollback to `tax-svc-v4.18.1` initiated; Redis cache hit rate recovers to 98% within 9 minutes."],
            ["14:59", "Checkout error rate returns to baseline (<0.05%); incident mitigated (total impact: 47 min)."],
        ], colWidths=[1.05 * inch, 5.75 * inch], style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E293B")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ])),
        Spacer(1, 8),

        Paragraph("3. What Went Well vs. What Failed", h_s),
        Paragraph(
            "• <b>Went well:</b> Automated alert fired within 7 minutes of deploy; instant artifact rollback worked cleanly without DB schema conflict.<br/>"
            "• <b>Failed:</b> (1) Canary only ran for 5 minutes at 1% traffic, too small to trigger thread exhaustion; (2) No circuit breaker or stale-cache fallback existed for upstream tax timeouts.",
            b_s
        ),

        Paragraph("4. Corrective Action Items (All Funded Within Existing Q2 Reliability Budget)", h_s),
        Table([
            ["Action Item", "Owner", "Due Date", "Ticket"],
            ["Enforce 2.5s upstream timeout + circuit breaker\nwith last-known-good tax table fallback", "M. Alvarez\n(Checkout Eng)", "May 1, 2026", "JIRA-8821"],
            ["Add automated Redis cache-miss >15%\nauto-rollback gate to canary pipeline", "D. Cho\n(Release Infra)", "May 8, 2026", "JIRA-8822"],
            ["Pre-warm shadow cache keys whenever\ntax schema version increments", "M. Alvarez\n(Checkout Eng)", "May 15, 2026", "JIRA-8823"],
        ], colWidths=[3.5 * inch, 1.45 * inch, 1.0 * inch, 0.85 * inch], style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#991B1B")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FEF2F2")]),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
            ("FONTSIZE", (0, 0), (-1, -1), 8.6),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ])),
    ]
    doc.build(story)
    return path


# =============================================================================
# HARD CASE 4: 15-PAGE EXEC DECK WITH SUBTLE APPENDIX CONTRADICTIONS
# =============================================================================

def build_hard_15p_exec_deck():
    """15-slide mostly sharp Executive QBR & FY27 Plan.
    Plants TWO subtle, realistic long-context contradictions:
      - Contradiction A: Slide 2 claims $4.2M Net New ARR & 118% NRR in Q4;
        Slide 14 Appendix Cohort Table reveals $1.1M was renewal pull-forward (true Net New ARR = $3.1M, NRR = 109%).
      - Contradiction B: Slide 6 claims 8 H1 Enterprise AEs add 'zero incremental OpEx above FY26 plan';
        Slide 13 Finance Appendix shows +$1.44M unbudgeted H1 Sales Headcount Variance for those 8 AEs."""
    path = os.path.join(HARD_DIR, "04_hard_15p_exec_deck_appendix_contradiction.pdf")
    c = canvas.Canvas(path, pagesize=(SLIDE_W, SLIDE_H))

    def hdr(kicker, title, num):
        c.setFillColor(colors.HexColor("#1D4ED8"))
        c.setFont("Helvetica-Bold", 9)
        c.drawString(0.7 * inch, SLIDE_H - 0.5 * inch, kicker.upper())
        draw_wrapped(c, title, 0.7 * inch, SLIDE_H - 0.65 * inch, SLIDE_W - 1.4 * inch,
                     "Helvetica-Bold", 18.5, 23, colors.HexColor("#0F172A"))
        c.setStrokeColor(colors.HexColor("#E2E8F0"))
        c.line(0.7 * inch, SLIDE_H - 1.35 * inch, SLIDE_W - 0.7 * inch, SLIDE_H - 1.35 * inch)
        c.setFillColor(colors.HexColor("#64748B"))
        c.setFont("Helvetica", 8.5)
        c.drawString(0.7 * inch, 0.35 * inch, "FY26 Q4 Business Review & FY27 Operating Plan — Executive Deck")
        c.drawRightString(SLIDE_W - 0.7 * inch, 0.35 * inch, f"{num} / 15")

    slides = [
        # 1
        ("Cover & Decision Ask",
         "Approve FY27 operating plan targeting $58M ending ARR (+29% YoY) with -$8.8M planned operating investment.",
         "<b>Context:</b> Annual Q4 review and FY27 budget lock for Board Finance Committee.<br/><br/>"
         "<b>Decision Needed by Dec 12:</b> Approve FY27 operating plan ($50.0M total OpEx envelope) and H1 hiring release for 8 Enterprise Account Executives (AEs)."),
        # 2 (CONTRADICTION A SOURCE: $4.2M Net New ARR, 118% NRR)
        ("Q4 Executive Summary",
         "Q4 closed at $45.0M ending ARR with $4.2M Net New ARR and 118% Net Revenue Retention.",
         "<b>Headline Q4 Performance:</b><br/><br/>"
         "• Ending ARR reached <b>$45.0M</b> (+27% YoY vs. $35.4M in Q4 FY25).<br/><br/>"
         "• <b>$4.2M Net New ARR</b> beat our $3.8M Q4 plan by 10.5%, led by strong Enterprise expansion.<br/><br/>"
         "• <b>Net Revenue Retention (NRR) climbed to 118%</b> (up from 111% in Q3), validating upmarket product-market fit.<br/><br/>"
         "• Gross margin held steady at 79.4%; ending cash balance stands at $62.0M."),
        # 3
        ("Segment Mix",
         "Enterprise (>1,000 seats) now contributes 62% of ARR, up from 49% twelve months ago.",
         "• Enterprise ARR grew from $17.3M to $27.9M (+61% YoY); average contract value rose from $68K to $94K.<br/><br/>"
         "• Mid-Market ARR grew modestly (+9% YoY to $12.1M) due to slower outbound conversion.<br/><br/>"
         "• SMB self-serve remained flat at $5.0M as marketing shifted spend toward Enterprise field events."),
        # 4
        ("Product Velocity",
         "Three Q4 releases—SSO federation, audit logs, and role permissions—unblocked 14 Enterprise deals.",
         "• Enterprise security bundle attached to 78% of new Q4 Enterprise contracts (adding +18% average ACV).<br/><br/>"
         "• Engineering shipped 94% of committed Q4 roadmap items; production uptime averaged 99.97%."),
        # 5
        ("Customer Health & Churn",
         "Gross logo retention improved to 92.5% as implementation cycle times dropped from 62 to 41 days.",
         "• Dedicated Solutions Architects reduced Enterprise onboarding duration by 21 days.<br/><br/>"
         "• Primary churn driver remains Mid-Market budget consolidation (68% of churned dollars)."),
        # 6 (CONTRADICTION B SOURCE: 8 Enterprise AEs with 'zero incremental OpEx above FY26 plan')
        ("FY27 Sales Capacity Plan",
         "Hiring 8 Enterprise AEs in H1 expands quota capacity by $9.6M with zero incremental OpEx above FY26 plan.",
         "• Each ramped Enterprise AE carries $1.2M annual quota with a 6-month ramp curve.<br/><br/>"
         "• <b>Budget Note:</b> All 8 H1 Enterprise AE hires are funded via reallocation from paused SMB paid-search spend, resulting in <b>zero incremental OpEx above our approved baseline plan</b>.<br/><br/>"
         "• Recruiting pipeline already has 14 final-round candidates across NY, SF, and London."),
        # 7
        ("Marketing Pipeline",
         "Enterprise qualified pipeline stands at $21.4M (3.4x Q1 coverage), driven by partner co-selling.",
         "• Cloud marketplace co-sell deals converted at 31% vs. 19% for direct cold outbound.<br/><br/>"
         "• Customer Acquisition Cost (CAC) payback improved from 17 months to 14.5 months in Enterprise."),
        # 8
        ("R&D Priorities FY27",
         "FY27 R&amp;D allocates 55% to Enterprise reliability/scale, 30% to AI workflow features, and 15% to tech debt.",
         "• Headcount remains flat at 68 engineers in H1; 6 backend hires gated on hitting Q2 ARR milestones.<br/><br/>"
         "• Infrastructure spend drops from 11.2% to 9.5% of revenue via reserved compute commitments."),
        # 9
        ("Competitive Landscape",
         "Win rate against Competitor X rose from 44% to 59% after launching native audit-log exports.",
         "• Remaining competitive loss driver (32% of losses) is lack of EU Frankfurt data residency, scheduled for Q2 FY27.<br/><br/>"
         "• Pricing remains 15–20% below legacy incumbents with faster deployment."),
        # 10
        ("Regional Expansion",
         "EMEA reached $8.4M ARR (+48% YoY) and breaks even on contribution margin in Q2 FY27.",
         "• London office (11 staff) closed 7 six-figure deals in Q4.<br/><br/>"
         "• Launching Frankfurt hosting region ($240K/yr infra cost) unlocks 9 stalled DACH prospects worth $1.6M."),
        # 11
        ("Key Risks & Mitigations",
         "Three FY27 risks—AE ramp lag, EU residency delay, and Mid-Market churn—carry explicit triggers.",
         "• <b>AE Ramp Lag:</b> If Q2 pipeline coverage drops below 3.0x, pause H2 hiring wave (Owner: CRO).<br/><br/>"
         "• <b>EU Hosting Slip:</b> Dedicated 4-engineer squad assigned; weekly exec milestone review (Owner: VP Eng).<br/><br/>"
         "• <b>Mid-Market Churn:</b> Shift 2 CSMs to automated health-trigger playbooks (Owner: VP CS)."),
        # 12
        ("FY27 P&L Summary",
         "FY27 plan delivers $58.0M ending ARR, 80% gross margin, and $50.0M total OpEx (-$8.8M operating investment).",
         "• Total Revenue projected at $51.5M (+28% YoY); Gross Profit $41.2M (80.0% gross margin).<br/><br/>"
         "• With $50.0M total OpEx, FY27 operating loss narrows to -$8.8M, ending year with $53.2M cash on hand (6+ years runway)."),
    ]

    for idx, (kicker, title, body) in enumerate(slides, start=1):
        hdr(kicker, title, idx)
        draw_wrapped(c, body, 0.8 * inch, 5.45 * inch, 11.6 * inch, font_size=13, leading=19.5, color=colors.HexColor("#1E293B"))
        c.showPage()

    # Slide 13: Finance Appendix — CONTRADICTION B (+$1.44M unbudgeted H1 Sales Headcount variance for the 8 AEs!)
    hdr("Appendix A — Finance OpEx Bridge",
        "FY27 H1 OpEx bridge reflects $1.44M unbudgeted Sales headcount variance for 8 new Enterprise AEs.", 13)
    t13 = Table([
        ["OpEx Line ($M)", "FY26 Baseline Plan", "FY27 Proposed H1 (Ann.)", "Variance vs. Plan", "Notes"],
        ["R&D Engineering", "$18.20M", "$18.20M", "$0.00M", "Flat H1 headcount (68 FTE)"],
        ["Marketing & Paid Search", "$9.40M", "$9.10M", "-$0.30M", "Modest SMB paid-search trim only"],
        ["Sales (incl. 8 New Ent. AEs)", "$13.60M", "$15.04M", "+$1.44M", "8 AEs @ $180K OTE + benefits (net new spend)"],
        ["G&A & Facilities", "$7.36M", "$7.66M", "+$0.30M", "London lease + audit fees"],
        ["Total OpEx Envelope", "$48.56M", "$50.00M", "+$1.44M", "Requires Board approval of +$1.44M variance"],
    ], colWidths=[2.6 * inch, 1.65 * inch, 1.95 * inch, 1.6 * inch, 4.0 * inch])
    t13.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#EFF6FF")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
    ]))
    t13.wrapOn(c, 12 * inch, 4.5 * inch)
    t13.drawOn(c, 0.7 * inch, 2.75 * inch)
    c.showPage()

    # Slide 14: Appendix Cohort Table — CONTRADICTION A ($3.1M true Net New ARR & 109% NRR vs Slide 2's $4.2M & 118%!)
    hdr("Appendix B — Q4 ARR Waterfall & Cohort Retention",
        "Detailed Q4 ARR cohort reconciliation separates organic expansion from Q1 renewal pull-forwards.", 14)
    t14 = Table([
        ["Q4 ARR Component", "Amount ($M)", "Classification / Footnote"],
        ["Beginning Q4 ARR (Oct 1)", "$41.90M", "Audited Q3 ending base"],
        ["New Logo Bookings", "+$2.60M", "19 new Enterprise & Mid-Market customers"],
        ["Organic Seat & Module Expansion", "+$1.35M", "True in-quarter expansion from existing cohorts"],
        ["Contraction & Logo Churn", "-$0.85M", "Mid-Market downsizing ($0.58M) + churn ($0.27M)"],
        ["True Q4 Net New ARR (Organic)", "+$3.10M", "Ending ARR = $45.00M; Organic NRR = 109%"],
        ["Memo: Early Multi-Year Renewals Pulled From Q1", "$1.10M", "Non-incremental renewal timing; excluded from true Net New ARR"],
    ], colWidths=[3.6 * inch, 1.6 * inch, 6.6 * inch])
    t14.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 5), (-1, 5), "Helvetica-Bold"),
        ("BACKGROUND", (0, 5), (-1, 5), colors.HexColor("#FEF3C7")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    t14.wrapOn(c, 12 * inch, 4.5 * inch)
    t14.drawOn(c, 0.7 * inch, 2.35 * inch)
    c.showPage()

    # Slide 15: Clean Appendix C (Glossary / Assumptions)
    hdr("Appendix C — Key Modeling Assumptions",
        "FY27 revenue model assumes 14.5-month Enterprise CAC payback and 6-month AE ramp.", 15)
    draw_wrapped(
        c,
        "• Standard Enterprise contract length: 24 months, billed annually upfront.<br/><br/>"
        "• Quota attainment modeled at 82% blended across ramped AEs (in line with FY26 actuals of 84%).<br/><br/>"
        "• FX rates held constant at Nov 2026 spot rates (EUR/USD 1.08, GBP/USD 1.27).",
        0.8 * inch, 5.3 * inch, 11.4 * inch, font_size=13, leading=19.5, color=colors.HexColor("#334155")
    )
    c.showPage()
    c.save()
    return path


if __name__ == "__main__":
    outputs = [
        build_hard_smooth_2026_slop(),
        build_hard_messy_human_genius_rfc(),
        build_hard_inform_only_postmortem(),
        build_hard_15p_exec_deck(),
    ]
    for p in outputs:
        print(f"Generated: {p} ({os.path.getsize(p):,} bytes)")
