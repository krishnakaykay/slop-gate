#!/usr/bin/env python3
"""
Generate 6 realistic calibration PDFs (3 Sharp positive exemplars + 3 AI-Slop negative examples)
for benchmarking and tuning Slop Gate (Gate 1).

Outputs:
  examples/slop/01_slop_deck_cloud_migration.pdf
  examples/slop/02_slop_memo_ai_support_copilot.pdf
  examples/slop/03_slop_deck_cross_org_api_deprecation.pdf
  examples/sharp/01_sharp_deck_cloud_migration.pdf
  examples/sharp/02_sharp_memo_ai_support_copilot.pdf
  examples/sharp/03_sharp_deck_cross_org_api_deprecation.pdf
"""

import io
import os
import tempfile

# Ensure matplotlib has a writable config dir inside sandbox
os.environ.setdefault("MPLCONFIGDIR", tempfile.mkdtemp(prefix="mpl_slopgate_"))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    Image,
    PageBreak,
    HRFlowable,
)
from reportlab.pdfgen import canvas

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SLOP_DIR = os.path.join(BASE_DIR, "slop")
SHARP_DIR = os.path.join(BASE_DIR, "sharp")
os.makedirs(SLOP_DIR, exist_ok=True)
os.makedirs(SHARP_DIR, exist_ok=True)

SLIDE_W, SLIDE_H = 13.333 * inch, 7.5 * inch  # Standard 16:9 widescreen slide


def fig_to_buf(fig, dpi=160):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf


def draw_wrapped_text(c, text, x, y, max_w, font_name="Helvetica", font_size=12, leading=16, color=colors.black):
    """Draw wrapped text using ReportLab Paragraph on a canvas, returning bottom y."""
    style = ParagraphStyle(
        "tmp",
        fontName=font_name,
        fontSize=font_size,
        leading=leading,
        textColor=color,
    )
    p = Paragraph(text, style)
    w, h = p.wrap(max_w, 1000)
    p.drawOn(c, x, y - h)
    return y - h


# =============================================================================
# CHART GENERATORS
# =============================================================================

def chart_slop_pie_and_flat_bar():
    """Deliberately bad visual: 8-slice crowded pie chart with distant legend + flat volume bar contradicting 'exponential growth'."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(9.2, 3.6), facecolor="#FFFDF5")

    # Bad 8-slice pie chart with garish colors and distant legend
    labels = [
        "Compute Tier A", "Compute Tier B", "Storage Hot", "Storage Cold",
        "Egress Fees", "CDC Licensing", "Ops Support", "Misc Overhead"
    ]
    sizes = [19, 15, 14, 13, 12, 11, 9, 7]
    bad_colors = ["#FF1744", "#FF9100", "#FFEA00", "#00E676", "#00B0FF", "#651FFF", "#F50057", "#795548"]
    wedges, _ = ax1.pie(
        sizes,
        colors=bad_colors,
        startangle=45,
        shadow=True,  # Chart junk!
        explode=[0.04] * 8,
    )
    ax1.set_title("Cost Distribution Overview", fontsize=11, fontweight="bold", color="#222")
    ax1.legend(
        wedges, labels, title="Cost Categories",
        loc="center left", bbox_to_anchor=(0.95, 0.5), fontsize=7.5
    )

    # Flat query volume chart that CONTRADICTS the slide's claim of "exponential demand acceleration"
    quarters = ["Q1 '25", "Q2 '25", "Q3 '25", "Q4 '25", "Q1 '26"]
    queries_k = [410, 418, 415, 422, 425]
    bars = ax2.bar(quarters, queries_k, color=["#E91E63", "#9C27B0", "#3F51B5", "#009688", "#FF5722"])
    ax2.set_ylim(390, 440)  # Truncated y-axis!
    ax2.set_title("Quarterly Query Metrics (K)", fontsize=11, fontweight="bold")
    ax2.grid(True, linestyle="--", alpha=0.7, color="#888")
    ax2.set_ylabel("Queries (Thousands)")

    plt.tight_layout(w_pad=4.5)
    return fig_to_buf(fig)


def chart_slop_noisy_architecture():
    """Deliberately cluttered decorative diagram with 12 overlapping boxes & excessive arrows."""
    fig, ax = plt.subplots(figsize=(5.8, 4.2), facecolor="#F8F9FA")
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)
    ax.axis("off")

    boxes = [
        (0.3, 8.2, 2.2, 1.1, "Legacy ERP\n& CRM Feeds", "#FFCDD2"),
        (3.0, 8.2, 2.2, 1.1, "CDC Ingestion\nMesh Layer", "#FFE0B2"),
        (5.7, 8.2, 2.2, 1.1, "Event Bus\nKafka / PubSub", "#FFF9C4"),
        (8.1, 8.2, 1.7, 1.1, "Raw Lake\nBronze", "#C8E6C9"),
        (0.3, 5.5, 2.1, 1.2, "ETL Orchestrator\nDAG Engine", "#B3E5FC"),
        (2.8, 5.5, 2.3, 1.2, "AI Semantic\nMetadata Hub", "#D1C4E9"),
        (5.5, 5.5, 2.2, 1.2, "Silver Curated\nTransform", "#F8BBD0"),
        (8.0, 5.5, 1.8, 1.2, "FinOps Cost\nGovernor", "#DCEDC8"),
        (0.4, 2.6, 2.2, 1.2, "Gold Mart\nBI Layer", "#B2DFDB"),
        (3.0, 2.6, 2.2, 1.2, "ML Feature\nStore v2", "#FFCCBC"),
        (5.6, 2.6, 2.1, 1.2, "Zero-Trust\nGovernance", "#CFD8DC"),
        (8.0, 2.6, 1.8, 1.2, "Exec Portal\n& APIs", "#FFE082"),
    ]
    for x, y, w, h, label, fc in boxes:
        rect = plt.Rectangle((x, y), w, h, facecolor=fc, edgecolor="#333", linewidth=1.2)
        ax.add_patch(rect)
        ax.text(x + w / 2, y + h / 2, label, ha="center", va="center", fontsize=7.5, fontweight="bold")

    # Spaghetti arrows
    arrow_pairs = [
        ((1.4, 8.2), (1.4, 6.7)), ((2.5, 8.7), (3.0, 8.7)), ((5.2, 8.7), (5.7, 8.7)),
        ((7.9, 8.7), (8.1, 8.7)), ((4.1, 8.2), (4.0, 6.7)), ((6.8, 8.2), (6.6, 6.7)),
        ((8.9, 8.2), (8.9, 6.7)), ((1.4, 5.5), (1.5, 3.8)), ((4.0, 5.5), (4.1, 3.8)),
        ((6.6, 5.5), (6.6, 3.8)), ((8.9, 5.5), (8.9, 3.8)), ((2.4, 6.1), (2.8, 6.1)),
        ((5.1, 6.1), (5.5, 6.1)), ((7.7, 6.1), (8.0, 6.1)), ((2.6, 3.2), (3.0, 3.2)),
        ((5.2, 3.2), (5.6, 3.2)), ((7.7, 3.2), (8.0, 3.2)), ((4.0, 5.5), (1.5, 3.8)),
        ((6.6, 5.5), (4.1, 3.8)), ((4.0, 8.2), (6.6, 6.7)),
    ]
    for (x1, y1), (x2, y2) in arrow_pairs:
        ax.annotate("", xy=(x2, y2), xytext=(x1, y1), arrowprops=dict(arrowstyle="->", color="#555", lw=0.9))

    ax.text(5.0, 0.9, "End-to-End Synergistic Helios Cloud Ecosystem Architecture", ha="center", fontsize=9, fontweight="bold", color="#222")
    ax.text(5.0, 0.3, "Seamless multi-tier data democratization across enterprise domains", ha="center", fontsize=7.5, color="#666")
    return fig_to_buf(fig)


def chart_sharp_storage_capacity():
    """Clean Cleveland-McGill line chart with direct annotations & capacity ceiling."""
    fig, ax = plt.subplots(figsize=(6.0, 3.6), facecolor="white")
    months = ["Sep '25", "Nov '25", "Jan '26", "Mar '26", "May '26", "Jul '26", "Aug '26"]
    util = [64, 70, 77, 83, 88, 92, 95]

    ax.plot(months[:5], util[:5], color="#1B365D", linewidth=2.6, marker="o", markersize=6, label="Actual")
    ax.plot(months[4:], util[4:], color="#C62828", linewidth=2.6, linestyle="--", marker="o", markersize=6, label="Forecast")
    ax.axhline(94, color="#C62828", linestyle=":", linewidth=1.6)
    ax.text(0.1, 95.3, "Hard cluster ceiling (94% — write throttling begins)", color="#C62828", fontsize=8.5, fontweight="bold")

    for i, (m, u) in enumerate(zip(months, util)):
        if i in (0, 3, 4, 6):
            ax.annotate(f"{u}%", (i, u), textcoords="offset points", xytext=(0, -15 if i == 6 else 8),
                        ha="center", fontsize=8.5, fontweight="bold", color="#C62828" if i == 6 else "#1B365D")

    ax.set_ylim(50, 105)
    ax.set_ylabel("Cluster Storage Utilization (%)", fontsize=9, color="#333")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#CCCCCC")
    ax.spines["bottom"].set_color("#CCCCCC")
    ax.tick_params(colors="#444", labelsize=8.5)
    ax.grid(axis="y", color="#EEEEEE", linewidth=0.8)
    ax.text(0.0, 1.04, "Helios Legacy Cluster Utilization (% of 480 TB limit)", transform=ax.transAxes,
            fontsize=9.5, fontweight="bold", color="#1B365D")
    return fig_to_buf(fig)


def chart_sharp_cost_comparison():
    """Clean horizontal bar chart with common baseline & direct labels."""
    fig, ax = plt.subplots(figsize=(6.2, 3.4), facecolor="white")
    categories = [
        "Status Quo\n(Keep Legacy + Scale Up)",
        "Option B\n(Vertical Hardware Upgrade)",
        "Option A (Recommended)\nManaged Lakehouse",
    ]
    annual_cost = [2.45, 2.10, 1.30]
    bar_colors = ["#90A4AE", "#B0BEC5", "#1B365D"]

    y_pos = np.arange(len(categories))
    bars = ax.barh(y_pos, annual_cost, height=0.52, color=bar_colors)
    ax.set_yticks(y_pos)
    ax.set_yticklabels(categories, fontsize=9, color="#222")
    ax.invert_yaxis()
    ax.set_xlim(0, 3.1)
    ax.set_xlabel("Annual Run-Rate Cost ($ Millions, USD)", fontsize=9, color="#333")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#CCCCCC")
    ax.spines["bottom"].set_color("#CCCCCC")
    ax.grid(axis="x", color="#EEEEEE", linewidth=0.8)

    annotations = [r"\$2.45M / yr", r"\$2.10M / yr (-\$0.35M)", r"\$1.30M / yr (-\$1.15M net)"]
    for bar, ann, col in zip(bars, annotations, ["#444", "#444", "#1B365D"]):
        ax.text(bar.get_width() + 0.06, bar.get_y() + bar.get_height() / 2, ann,
                va="center", fontsize=9, fontweight="bold", color=col)

    ax.text(0.0, 1.06, "Annual Run-Rate Analytics Cost After Migration ($M/yr)", transform=ax.transAxes,
            fontsize=9.5, fontweight="bold", color="#1B365D")
    return fig_to_buf(fig)


def chart_sharp_handle_time():
    """Clean trend chart for the Sharp Amazon-style AI Support Copilot Memo."""
    fig, ax = plt.subplots(figsize=(5.6, 2.7), facecolor="white")
    quarters = ["Q1 '25", "Q2 '25", "Q3 '25", "Q4 '25", "Q1 '26"]
    aht = [6.4, 6.9, 7.6, 8.4, 9.1]
    target = [6.5] * len(quarters)

    ax.plot(quarters, aht, color="#1B365D", linewidth=2.4, marker="o", markersize=5.5)
    ax.plot(quarters, target, color="#2E7D32", linestyle="--", linewidth=1.4)
    ax.text(0.05, 6.1, "Operational SLA target (6.5 min)", color="#2E7D32", fontsize=8, fontweight="bold")
    for i, v in enumerate(aht):
        ax.annotate(f"{v:.1f}m", (i, v), textcoords="offset points", xytext=(0, 7),
                    ha="center", fontsize=8.5, fontweight="bold", color="#1B365D")
    ax.set_ylim(5.2, 10.4)
    ax.set_ylabel("Median Handle Time (min)", fontsize=8.5)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", color="#EEEEEE")
    ax.set_title("Tier-1 Median Handle Time Grew 42% in 12 Months (n = 142K tickets/mo)",
                 fontsize=9, fontweight="bold", color="#1B365D", loc="left", pad=8)
    return fig_to_buf(fig)


# =============================================================================
# NEGATIVE EXAMPLE 1: SLOP SLIDE DECK (Cloud Migration — Project Helios)
# =============================================================================

def build_slop_deck_cloud_migration():
    path = os.path.join(SLOP_DIR, "01_slop_deck_cloud_migration.pdf")
    c = canvas.Canvas(path, pagesize=(SLIDE_W, SLIDE_H))

    def header_slop(title, page_num):
        c.setFillColor(colors.HexColor("#1E3A8A"))
        c.rect(0, SLIDE_H - 0.9 * inch, SLIDE_W, 0.9 * inch, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 24)
        c.drawString(0.6 * inch, SLIDE_H - 0.6 * inch, title)
        c.setFillColor(colors.HexColor("#999999"))
        c.setFont("Helvetica", 9)
        c.drawRightString(SLIDE_W - 0.4 * inch, 0.3 * inch, f"Confidential — Project Helios | {page_num}")

    # Slide 1: Generic Cover (No Context, No Ask)
    c.setFillColor(colors.HexColor("#0F172A"))
    c.rect(0, 0, SLIDE_W, SLIDE_H, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 38)
    c.drawString(1.0 * inch, 4.7 * inch, "Project Helios: Next-Generation")
    c.drawString(1.0 * inch, 4.1 * inch, "Enterprise Data Transformation")
    c.setFont("Helvetica", 18)
    c.setFillColor(colors.HexColor("#94A3B8"))
    c.drawString(1.0 * inch, 3.3 * inch, "A Comprehensive Strategic Overview & Holistic Synergy Roadmap")
    c.setFont("Helvetica", 12)
    c.drawString(1.0 * inch, 1.2 * inch, "Data Platform Transformation Office | Q2 2026")
    c.showPage()

    # Slide 2: Passive Title ("Overview"), Unexpanded Acronyms, Weasel Words, Contradictory $2.4M Q3 claim
    header_slop("Overview", 2)
    bullets_s2 = [
        "In today's rapidly evolving digital landscape, leveraging modern cloud-native DWH and CDC capabilities is critically essential for driving synergistic enterprise agility and best-in-class operational excellence across all business verticals.",
        "Project Helios represents a transformative, holistic initiative designed to seamlessly modernize our legacy E2E analytics stack, substantially unlocking unprecedented scalability and world-class FinOps optimization.",
        "Nearly all internal stakeholders have expressed overwhelmingly positive sentiment regarding the proposed modernization, which will dramatically accelerate time-to-insight and significantly enhance executive decision-making.",
        "Preliminary directional modeling indicates that migrating to the next-gen platform will deliver $2.4M in annual cost savings starting in Q3 2026 while vastly improving SLA compliance and system reliability.",
        "By proactively embracing this innovative paradigm shift, the organization will future-proof its data ecosystem and unlock massive competitive advantages across multiple strategic workstreams.",
        "Furthermore, the transition directly aligns with broader corporate digitalization mandates and establishes a robust foundation for future generative AI and advanced predictive analytics initiatives."
    ]
    y = SLIDE_H - 1.25 * inch
    for b in bullets_s2:
        y = draw_wrapped_text(c, f"•  {b}", 0.65 * inch, y, SLIDE_W - 1.3 * inch, font_size=12.5, leading=16.5, color=colors.HexColor("#1F2937"))
        y -= 0.14 * inch
    c.showPage()

    # Slide 3: Wall of text + Cluttered 12-box spaghetti diagram (High Edge Density & Quadtree Clutter!)
    header_slop("Strategic Architecture", 3)
    arch_buf = chart_slop_noisy_architecture()
    c.drawImage(Image(arch_buf).filename if False else None, 0, 0) if False else None
    from reportlab.lib.utils import ImageReader
    c.drawImage(ImageReader(arch_buf), 6.7 * inch, 1.3 * inch, width=6.1 * inch, height=4.9 * inch, preserveAspectRatio=True)

    dense_bullets = [
        "Our multi-layered medallion architecture leverages cutting-edge CDC pipelines to continuously ingest heterogeneous operational payloads from legacy ERP, CRM, and third-party SaaS endpoints with ultra-low latency.",
        "The AI Semantic Metadata Hub dynamically harmonizes cross-domain schemas while enforcing zero-trust RBAC/ABAC governance, automated PII tokenization, and real-time lineage tracking.",
        "Distributed compute clusters automatically autoscale elastically to accommodate unpredictable burst workloads while our FinOps Governor continuously right-sizes warehouse tiers.",
        "Silver and Gold curated transformation layers decouple analytical consumption from transactional workloads, dramatically reducing query contention for nearly all downstream BI dashboards.",
        "Self-service ML Feature Store integration empowers data scientists to rapidly operationalize predictive models without manual feature engineering bottlenecks.",
        "Unified observability telemetry monitors end-to-end DAG SLAs, schema drift anomalies, and data freshness thresholds across every enterprise domain.",
        "Automated CI/CD infrastructure-as-code templates streamline deployment lifecycles and eliminate manual configuration drift across dev, staging, and prod.",
        "Multi-region active-active failover guarantees robust business continuity and seamless disaster recovery for mission-critical reporting workflows."
    ]
    y = SLIDE_H - 1.18 * inch
    for b in dense_bullets:
        y = draw_wrapped_text(c, f"• {b}", 0.5 * inch, y, 5.95 * inch, font_size=9.5, leading=12.5, color=colors.HexColor("#111827"))
        y -= 0.08 * inch
    c.showPage()

    # Slide 4: Terrible Pie + Flat Volume Chart contradicting "exponential demand" + Table contradicting $2.4M savings!
    header_slop("Financial Projections", 4)
    pie_buf = chart_slop_pie_and_flat_bar()
    c.drawImage(ImageReader(pie_buf), 0.5 * inch, 3.15 * inch, width=12.3 * inch, height=3.3 * inch, preserveAspectRatio=True)

    # Contradictory narrative claim vs flat chart
    draw_wrapped_text(
        c,
        "<b>Key Financial Highlights:</b> As clearly evidenced by the exponential query demand acceleration shown above, continuing on our legacy cluster is completely unsustainable. "
        "Transitioning to the managed lakehouse drives massive structural efficiency and significantly lowers TCO across all cost categories.",
        0.6 * inch, 2.95 * inch, 6.2 * inch, font_size=11, leading=14.5, color=colors.HexColor("#1F2937")
    )

    # Table whose numbers sum to $1.1M net savings (CONTRADICTS Slide 2's $2.4M claim!)
    tbl_data = [
        ["Cost Line", "Current ($M)", "Proposed ($M)", "Net Savings ($M)"],
        ["Compute & Warehouse", "$1.40M", "$0.80M", "$0.60M"],
        ["Storage & Backup", "$0.65M", "$0.35M", "$0.30M"],
        ["Licensing & Ops", "$0.55M", "$0.35M", "$0.20M"],
        ["Total Annual Run-Rate", "$2.60M", "$1.50M", "$1.10M"],
    ]
    t = Table(tbl_data, colWidths=[1.8 * inch, 1.15 * inch, 1.2 * inch, 1.35 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E3A8A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#E0E7FF")),
        ("GRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#CBD5E1")),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
    ]))
    t.wrapOn(c, 6 * inch, 3 * inch)
    t.drawOn(c, 7.1 * inch, 1.15 * inch)
    c.showPage()

    # Slide 5: Passive Title ("Implementation Roadmap") + Contradictory Q1 2027 timeline (Slide 2 said Q3 2026!)
    header_slop("Implementation Roadmap", 5)
    road_data = [
        ["Phase", "Workstream Description", "Timeline", "Status"],
        ["Phase 1", "Discovery, Stakeholder Alignment & Vendor Selection", "Q2 2026 – Q3 2026", "In Progress"],
        ["Phase 2", "Core Platform Provisioning & CDC Schema Setup", "Q3 2026 – Q4 2026", "Planned"],
        ["Phase 3", "Parallel Shadow Validation & BI Dashboard Migration", "Q4 2026 – Q1 2027", "Planned"],
        ["Phase 4", "Full Production Cutover & Legacy Decommissioning", "Q1 2027", "Planned"],
    ]
    rt = Table(road_data, colWidths=[1.3 * inch, 6.2 * inch, 2.5 * inch, 1.8 * inch])
    rt.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#334155")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ("FONTSIZE", (0, 0), (-1, -1), 11.5),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    rt.wrapOn(c, 12 * inch, 5 * inch)
    rt.drawOn(c, 0.75 * inch, 3.6 * inch)
    draw_wrapped_text(
        c,
        "Our agile, phased methodology ensures a seamless transition with virtually zero disruption to business operations. "
        "Cross-functional working groups will collaborate closely to guarantee best-in-class execution velocity and robust risk mitigation throughout every milestone.",
        0.75 * inch, 2.9 * inch, 11.8 * inch, font_size=13, leading=18, color=colors.HexColor("#374151")
    )
    c.showPage()

    # Slide 6: Vague Next Steps (Zero owner, zero date, zero ask)
    header_slop("Next Steps", 6)
    ns = [
        "Continue socializing the Project Helios vision across key business units to build broad strategic alignment.",
        "Finalize vendor negotiations and evaluate comprehensive licensing constructs to maximize value.",
        "Establish a cross-functional Center of Excellence (CoE) to drive ongoing governance and best practices.",
        "Revisit budget requirements and resource allocations in upcoming quarterly planning cycles.",
        "Thank you! Questions & Discussion."
    ]
    y = SLIDE_H - 1.6 * inch
    for item in ns:
        y = draw_wrapped_text(c, f"•  {item}", 0.8 * inch, y, 11.5 * inch, font_size=15, leading=21, color=colors.HexColor("#1F2937"))
        y -= 0.28 * inch
    c.showPage()
    c.save()
    return path


# =============================================================================
# NEGATIVE EXAMPLE 2: SLOP NARRATIVE MEMO (AI Customer Support Copilot)
# =============================================================================

def build_slop_memo_ai_support_copilot():
    path = os.path.join(SLOP_DIR, "02_slop_memo_ai_support_copilot.pdf")
    doc = SimpleDocTemplate(path, pagesize=letter, leftMargin=0.8 * inch, rightMargin=0.8 * inch,
                            topMargin=0.8 * inch, bottomMargin=0.8 * inch)
    styles = getSampleStyleSheet()
    title_s = ParagraphStyle("t", parent=styles["Title"], fontSize=18, alignment=TA_LEFT, textColor=colors.HexColor("#1E293B"))
    h2_s = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=13, spaceBefore=14, spaceAfter=6, textColor=colors.HexColor("#1E3A8A"))
    body_s = ParagraphStyle("b", parent=styles["BodyText"], fontSize=10.2, leading=14.5, alignment=TA_JUSTIFY, spaceAfter=10)

    story = [
        Paragraph("Strategic Initiative Proposal: Next-Gen AI Customer Support Copilot", title_s),
        Paragraph("<i>Prepared by Customer Experience Transformation Team | May 2026</i>",
                  ParagraphStyle("sub", parent=styles["Normal"], fontSize=9.5, textColor=colors.gray, spaceAfter=14)),
        HRFlowable(width="100%", color=colors.HexColor("#CBD5E1")),
        Spacer(1, 10),

        Paragraph("Background and Industry Landscape", h2_s),
        # Deliberate long >35-word sentences, dense nominalizations, weasel words, unexpanded acronyms, wall-of-text
        Paragraph(
            "In today's hyper-competitive enterprise software landscape, organizations across nearly all verticals are rapidly "
            "recognizing that delivering seamless, best-in-class customer experiences is critically important for sustaining long-term "
            "retention and unlocking synergistic revenue expansion opportunities over the coming fiscal cycles. Due to the fact that "
            "customer expectations have evolved dramatically in recent years, legacy Tier-1 and Tier-2 support workflows relying on "
            "manual KB searches and fragmented BPO escalation processes have increasingly struggled to maintain optimal AHT and FCR "
            "benchmarks across our growing global footprint. Furthermore, in order to remain competitive against disruptive peers who "
            "are already operationalizing generative AI at massive scale, our organization must proactively embrace a comprehensive, "
            "holistic transformation of our service delivery model rather than continuing to rely on incremental tactical fixes that "
            "fail to address the underlying structural friction experienced by both frontline agents and end customers. Almost all "
            "industry analysts strongly agree that deploying an intelligent RAG-powered copilot represents a foundational paradigm "
            "shift that significantly enhances agent productivity while vastly improving overall CSAT metrics across every customer "
            "segment. Crucially, this initiative is designed for rapid, seamless deployment using our existing cloud infrastructure "
            "with zero incremental headcount impact, making it an extraordinarily compelling and low-risk investment for the business.",
            body_s
        ),

        Paragraph("Proposed Solution Overview", h2_s),
        Paragraph(
            "The proposed AI Support Copilot will seamlessly integrate into our current CRM workspace in order to provide real-time, "
            "contextually aware response drafting, automated ticket summarization, and intelligent policy lookup capabilities that "
            "substantially reduce cognitive burden for support specialists handling complex multi-channel inquiries. By leveraging "
            "state-of-the-art large language models connected directly to our internal KB repositories, the copilot will dramatically "
            "streamline troubleshooting workflows and empower even newly onboarded agents to perform at world-class levels almost "
            "immediately upon deployment. Early anecdotal feedback from several team leads suggests that agents would strongly welcome "
            "automated drafting assistance, and directional vendor case studies indicate that similar enterprises have achieved up to "
            "a 40% improvement in overall efficiency and massively faster TTR across comparable ticket volumes. Moreover, the platform "
            "will feature robust enterprise-grade guardrails, seamless PII redaction, and continuous learning loops that progressively "
            "optimize accuracy over time without requiring heavy manual intervention from operations teams. This holistic approach "
            "ensures that our support organization scales effortlessly as customer volume expands while delivering consistently "
            "exceptional experiences that strengthen brand loyalty and differentiate our product offering in the marketplace.",
            body_s
        ),

        Paragraph("Operational Synergy and Implementation Considerations", h2_s),
        Paragraph(
            "Implementing the AI Support Copilot across global Tier-1 and Tier-2 queues will follow a structured, agile rollout "
            "methodology emphasizing close cross-functional alignment between Support Operations, IT Security, Legal, and Engineering "
            "stakeholders to ensure smooth adoption and strong change management outcomes. While the core vendor platform offers "
            "turnkey connectors for standard ticketing interfaces, productionizing the custom RAG retrieval pipeline over our legacy "
            "policy repositories will require hiring 2 dedicated ML platform engineers and completing a mandatory 6-month SOC2 Type II "
            "security and data-residency audit before live customer ticket data can be processed in production environments. "  # CONTRADICTS Page 1's "zero headcount impact and rapid deployment with existing infrastructure"!
            "In addition, regional BPO partners will need to complete comprehensive enablement workshops so that workflow transitions "
            "occur seamlessly without adversely affecting seasonal service-level commitments during peak renewal periods. Despite these "
            "standard coordination items, the overwhelming strategic upside and transformative long-term value of modernizing our "
            "customer support capabilities far outweigh any minor transitional friction encountered during initial onboarding.",
            body_s
        ),

        PageBreak(),
        Paragraph("Expected Impact and Resource Requirements", h2_s),
        Paragraph(
            "From a financial and strategic perspective, deploying the AI Support Copilot is projected to unlock substantial cost "
            "avoidance, significantly elevate agent satisfaction, and dramatically boost CSAT across nearly all enterprise accounts "
            "within the first year of full-scale adoption. Because automation reduces repetitive manual research, support specialists "
            "can dedicate meaningfully more time to high-empathy consultative interactions that deepen customer relationships and "
            "uncover valuable upsell signals for our account management teams. To initiate vendor contracting, recruit the two ML "
            "platform engineers, and kick off the security audit and pilot integration workstreams, we are requesting leadership "
            "approval for $480,000 in unbudgeted FY26 funding along with priority engineering allocation starting next month. "  # BURIED ASK ON PAGE 2/END!
            "Upon approval, the transformation working group will convene weekly steering committees to track directional adoption "
            "trends, refine prompt engineering best practices, and identify additional high-impact AI use cases across the broader "
            "customer success organization.",
            body_s
        ),

        Paragraph("Conclusion", h2_s),
        Paragraph(
            "In summary, the AI Customer Support Copilot represents a rare, high-leverage opportunity to modernize our service "
            "infrastructure, empower our frontline workforce, and deliver truly world-class customer experiences at scale. By acting "
            "decisively now, we position the company at the forefront of AI-enabled customer operations while laying a robust, scalable "
            "foundation for sustained operational excellence in the years ahead. We look forward to aligning with leadership on this "
            "exciting journey and moving forward expeditiously.",
            body_s
        ),
    ]
    doc.build(story)
    return path


# =============================================================================
# NEGATIVE EXAMPLE 3: SUBTLE CROSS-ORG SLOP DECK (Legacy Auth API v2 Deprecation)
# =============================================================================

def build_slop_deck_cross_org():
    """Visually tidy deck, but terrible for a 'Colleague in Another Division/Org':
    internal platform jargon, buried impact, conflicting deadlines (Oct 15 vs Nov 30), vague ownership."""
    path = os.path.join(SLOP_DIR, "03_slop_deck_cross_org_api_deprecation.pdf")
    c = canvas.Canvas(path, pagesize=(SLIDE_W, SLIDE_H))

    def hdr(title, num):
        c.setFillColor(colors.HexColor("#111827"))
        c.setFont("Helvetica-Bold", 22)
        c.drawString(0.7 * inch, SLIDE_H - 0.85 * inch, title)
        c.setStrokeColor(colors.HexColor("#E5E7EB"))
        c.line(0.7 * inch, SLIDE_H - 1.05 * inch, SLIDE_W - 0.7 * inch, SLIDE_H - 1.05 * inch)
        c.setFillColor(colors.HexColor("#9CA3AF"))
        c.setFont("Helvetica", 9)
        c.drawRightString(SLIDE_W - 0.7 * inch, 0.35 * inch, f"Core Platform Identity Team | Slide {num}")

    # Slide 1: Cover with zero mention of Payments Division impact
    hdr("Vortex Identity Modernization & Legacy Auth Sunset", 1)
    draw_wrapped_text(
        c,
        "Transitioning internal service-to-service traffic from Legacy Auth v2 to Gatekeeper-v3 ZTA-Mesh Federation.<br/><br/>"
        "<i>Prepared by Core Platform IAM Architecture Group — Q2 2026</i>",
        0.7 * inch, 5.2 * inch, 11.5 * inch, font_size=16, leading=24, color=colors.HexColor("#4B5563")
    )
    c.showPage()

    # Slide 2: Heavy internal jargon, deadline says Oct 15 (contradicts Slide 5's Nov 30!)
    hdr("Platform Context & Timeline", 2)
    s2 = [
        "As part of Project Vortex, Core Platform is deprecating Legacy Auth v2 token minting in favor of Gatekeeper-v3 with automated MTLS-rotator sidecars and ZTA-mesh attestation.",
        "Legacy Auth v2 relies on static HMAC-signed SAML-bridge assertions that no longer meet our internal IAM-federation hardening posture.",
        "All downstream consumers across internal divisions must complete migration before full Legacy Auth v2 sunset on October 15, 2026.",
        "Migration dramatically simplifies credential lifecycle management and provides substantially stronger cryptographic assurance."
    ]
    y = SLIDE_H - 1.5 * inch
    for item in s2:
        y = draw_wrapped_text(c, f"•  {item}", 0.8 * inch, y, 11.4 * inch, font_size=14, leading=20, color=colors.HexColor("#1F2937"))
        y -= 0.25 * inch
    c.showPage()

    # Slide 3: Deep platform internals irrelevant to Payments reader ("So What?" failure)
    hdr("Gatekeeper-v3 Control Plane Details", 3)
    s3 = [
        "Gatekeeper-v3 utilizes SPIFFE-compliant X.509 SVID bundles issued via Envoy SDS over local UDS sockets.",
        "Policy evaluation shifts from central PDP roundtrips to WASM OPA filters cached at the ingress mesh layer.",
        "Token TTL drops from 24 hours to 15 minutes with background jittered rotation handled by MTLS-rotator daemonsets.",
        "Control plane telemetry emits OpenTelemetry spans directly to the Vortex-Obs Prometheus cluster."
    ]
    y = SLIDE_H - 1.5 * inch
    for item in s3:
        y = draw_wrapped_text(c, f"•  {item}", 0.8 * inch, y, 11.4 * inch, font_size=14, leading=20, color=colors.HexColor("#1F2937"))
        y -= 0.25 * inch
    c.showPage()

    # Slide 4: Finally mentions Payments (buried on Slide 4!), still vague on exact action
    hdr("Downstream Consumer Impact", 4)
    s4 = [
        "Several services in Commerce, Fulfillment, and Payments currently call Legacy Auth v2 endpoints for internal token exchange.",
        "Unmigrated callers will experience 401/403 authentication rejections once the legacy bridge is decommissioned.",
        "Partner teams should review their service manifests, adopt the new SDK, and validate staging traffic accordingly.",
        "Additional documentation is available across the internal Vortex Confluence spaces."
    ]
    y = SLIDE_H - 1.5 * inch
    for item in s4:
        y = draw_wrapped_text(c, f"•  {item}", 0.8 * inch, y, 11.4 * inch, font_size=14, leading=20, color=colors.HexColor("#1F2937"))
        y -= 0.25 * inch
    c.showPage()

    # Slide 5: Contradictory Nov 30 date for Payments + vague ownership
    hdr("Migration Schedule & Coordination", 5)
    tbl = Table([
        ["Division", "Scope", "Target Cutover", "Owner"],
        ["Commerce", "Checkout & Cart", "Sep 30, 2026", "Division Leads"],
        ["Fulfillment", "Warehouse APIs", "Oct 15, 2026", "Division Leads"],
        ["Payments", "Ledger & Settlement", "Nov 30, 2026", "Payments Team"],
    ], colWidths=[2.3 * inch, 3.6 * inch, 2.6 * inch, 2.8 * inch])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F2937")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")),
        ("FONTSIZE", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    tbl.wrapOn(c, 12 * inch, 4 * inch)
    tbl.drawOn(c, 0.8 * inch, 3.7 * inch)
    draw_wrapped_text(
        c,
        "Teams should coordinate seamlessly with Core Platform to ensure a smooth transition and avoid service disruptions.",
        0.8 * inch, 2.8 * inch, 11.5 * inch, font_size=13.5, leading=19, color=colors.HexColor("#374151")
    )
    c.showPage()
    c.save()
    return path


# =============================================================================
# POSITIVE EXAMPLE 1: SHARP SLIDE DECK (McKinsey Pyramid + Assertion-Evidence)
# =============================================================================

def build_sharp_deck_cloud_migration():
    """A/B counterpart to Slop #1: McKinsey Pyramid Principle, 100% Action Titles,
    SCQA + explicit Ask on Slide 1, clean charts, 100% reconciled numbers, explicit risks."""
    path = os.path.join(SHARP_DIR, "01_sharp_deck_cloud_migration.pdf")
    c = canvas.Canvas(path, pagesize=(SLIDE_W, SLIDE_H))
    from reportlab.lib.utils import ImageReader

    def hdr(kicker, action_title, page_num):
        # Kicker
        c.setFillColor(colors.HexColor("#2563EB"))
        c.setFont("Helvetica-Bold", 9.5)
        c.drawString(0.7 * inch, SLIDE_H - 0.5 * inch, kicker.upper())
        # Action title (complete takeaway sentence)
        draw_wrapped_text(
            c, action_title, 0.7 * inch, SLIDE_H - 0.65 * inch, SLIDE_W - 1.4 * inch,
            font_name="Helvetica-Bold", font_size=19, leading=24, color=colors.HexColor("#0F172A")
        )
        c.setStrokeColor(colors.HexColor("#E2E8F0"))
        c.setLineWidth(1)
        c.line(0.7 * inch, SLIDE_H - 1.38 * inch, SLIDE_W - 0.7 * inch, SLIDE_H - 1.38 * inch)
        # Footer
        c.setFillColor(colors.HexColor("#64748B"))
        c.setFont("Helvetica", 8.5)
        c.drawString(0.7 * inch, 0.35 * inch, "Project Helios (Enterprise Analytics Warehouse Migration) — Executive Decision Brief")
        c.drawRightString(SLIDE_W - 0.7 * inch, 0.35 * inch, f"{page_num} / 6")

    # Slide 1: SCQA Executive Summary + Explicit Decision Ask
    hdr(
        "Executive Summary & Decision Ask",
        "Approve $620K migration to a managed lakehouse to avoid an Aug 2026 storage outage and cut run-rate cost by $1.15M/yr.",
        1
    )
    # Context Re-Anchoring Box (for busy leadership returning after 2–4 weeks)
    c.setFillColor(colors.HexColor("#F8FAFC"))
    c.setStrokeColor(colors.HexColor("#CBD5E1"))
    c.roundRect(0.7 * inch, 4.75 * inch, 11.9 * inch, 1.15 * inch, 6, fill=1, stroke=1)
    draw_wrapped_text(
        c,
        "<b>Context Reminder (Project Helios):</b> Helios is our legacy on-premise analytics warehouse supporting Finance, Supply Chain, and Merchandising reporting (480 TB cap; $2.45M/yr current run-rate). "
        "<b>Decision Needed by May 15:</b> Approve $620K one-time migration budget and a 3-week analytics feature freeze in Oct 2026.",
        0.9 * inch, 5.72 * inch, 11.5 * inch, font_size=11.5, leading=16, color=colors.HexColor("#1E293B")
    )

    # 3 MECE Supporting Pillars
    pillars = [
        ("1. Urgent Bottleneck", "Cluster hits 94% write-throttling cap in Aug 2026",
         "Storage grew 64% → 88% in 8 months due to hourly clickstream retention. Short-term archival buys 90 days (to Nov 2026), not a permanent fix."),
        ("2. Compelling Economics", "$1.15M/yr net run-rate savings (6.5-month payback)",
         "Managed lakehouse lowers annual run-rate from $2.45M to $1.30M, beating vertical hardware expansion ($2.10M/yr) by $800K/yr."),
        ("3. Controlled Cutover", "Dual-run cutover completes Nov 15, 2026",
         "30-day shadow validation reconciles Finance KPIs before switching BI traffic. Full rollback to legacy cluster preserved for 14 days."),
    ]
    for i, (head, stat, desc) in enumerate(pillars):
        x = 0.7 * inch + i * 4.08 * inch
        c.setFillColor(colors.white)
        c.setStrokeColor(colors.HexColor("#1B365D") if i == 1 else colors.HexColor("#CBD5E1"))
        c.setLineWidth(1.5 if i == 1 else 1)
        c.roundRect(x, 1.25 * inch, 3.78 * inch, 3.15 * inch, 6, fill=1, stroke=1)
        draw_wrapped_text(c, head, x + 0.22 * inch, 4.18 * inch, 3.35 * inch, "Helvetica-Bold", 11, 14, colors.HexColor("#2563EB"))
        draw_wrapped_text(c, stat, x + 0.22 * inch, 3.85 * inch, 3.35 * inch, "Helvetica-Bold", 13.5, 17.5, colors.HexColor("#0F172A"))
        draw_wrapped_text(c, desc, x + 0.22 * inch, 3.1 * inch, 3.35 * inch, "Helvetica", 10.5, 15, colors.HexColor("#334155"))
    c.showPage()

    # Slide 2: Assertion-Evidence (Capacity Cliff)
    hdr(
        "1. The Complication",
        "Legacy Helios cluster hits its 94% write-throttling ceiling in Aug 2026, risking daily Finance close delays.",
        2
    )
    cap_buf = chart_sharp_storage_capacity()
    c.drawImage(ImageReader(cap_buf), 0.7 * inch, 1.5 * inch, width=7.0 * inch, height=4.2 * inch, preserveAspectRatio=True)

    c.setFillColor(colors.HexColor("#FEF2F2"))
    c.setStrokeColor(colors.HexColor("#FECACA"))
    c.roundRect(8.1 * inch, 3.65 * inch, 4.5 * inch, 2.0 * inch, 6, fill=1, stroke=1)
    draw_wrapped_text(
        c,
        "<b>Why Now?</b><br/>• 94% utilization triggers automatic write throttling on nightly ETL jobs.<br/>"
        "• Cold-archiving 2022–2023 logs frees 11% capacity — buying exactly <b>90 days (until Nov 2026)</b>.<br/>"
        "• Waiting past May 15 misses the Nov 2026 cutover window.",
        8.3 * inch, 5.45 * inch, 4.1 * inch, font_size=10.8, leading=15.5, color=colors.HexColor("#7F1D1D")
    )
    draw_wrapped_text(
        c,
        "<b>Source:</b> Infrastructure telemetry (Sep 2025–May 2026 actuals; linear 3.1%/mo forecast).",
        8.1 * inch, 3.25 * inch, 4.5 * inch, font_size=9.5, leading=13, color=colors.HexColor("#64748B")
    )
    c.showPage()

    # Slide 3: Assertion-Evidence (Economics — Reconciled!)
    hdr(
        "2. Economic Comparison",
        "Managed lakehouse (Option A) cuts annual run-rate by $1.15M vs. status quo and pays back in 6.5 months.",
        3
    )
    cost_buf = chart_sharp_cost_comparison()
    c.drawImage(ImageReader(cost_buf), 0.7 * inch, 1.8 * inch, width=6.7 * inch, height=3.9 * inch, preserveAspectRatio=True)

    # Reconciled Table (matches Slide 1 & Slide 3 chart to the exact dollar!)
    econ_tbl = Table([
        ["Cost Line ($M / yr)", "Status Quo", "Option A", "Delta"],
        ["Compute & Warehouse", "$1.35M", "$0.70M", "-$0.65M"],
        ["Storage & Backup", "$0.60M", "$0.25M", "-$0.35M"],
        ["Licensing & Ops", "$0.50M", "$0.35M", "-$0.15M"],
        ["Total Annual Run-Rate", "$2.45M", "$1.30M", "-$1.15M"],
        ["One-Time Migration", "$0.00M", "$0.62M", "6.5 mo payback"],
    ], colWidths=[2.0 * inch, 0.95 * inch, 0.95 * inch, 1.15 * inch])
    econ_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1B365D")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 4), (-1, 4), "Helvetica-Bold"),
        ("BACKGROUND", (0, 4), (-1, 4), colors.HexColor("#EFF6FF")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ("FONTSIZE", (0, 0), (-1, -1), 9.2),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    econ_tbl.wrapOn(c, 5.2 * inch, 4 * inch)
    econ_tbl.drawOn(c, 7.6 * inch, 2.75 * inch)
    draw_wrapped_text(
        c,
        "<b>Why we ruled out Option B (Vertical Upgrade):</b> Costs $490K upfront for new on-prem nodes, saves only $0.35M/yr, and still hits hardware end-of-life in 2028.",
        7.6 * inch, 2.45 * inch, 5.0 * inch, font_size=10, leading=14, color=colors.HexColor("#334155")
    )
    c.showPage()

    # Slide 4: Architecture — Simple 3-Step Visual Logic (No 12-box clutter!)
    hdr(
        "3. Migration Approach",
        "A 3-step shadow cutover moves 185 production tables with zero BI downtime and a 14-day rollback buffer.",
        4
    )
    steps = [
        ("Step 1: Cold Archive & Mirror", "May 18 – Jul 31, 2026",
         "• Archive 2022–2023 raw logs to object storage (frees 11% headroom immediately).\n• Stand up managed lakehouse and enable Change Data Capture (CDC) replication."),
        ("Step 2: Shadow Validation", "Aug 1 – Oct 15, 2026",
         "• Run top 24 Finance & Supply Chain dashboards in parallel against legacy & lakehouse.\n• Automated diff checks enforce <0.01% variance before sign-off."),
        ("Step 3: Cutover & Decommission", "Oct 16 – Nov 15, 2026",
         "• 3-week analytics feature freeze (Oct 16–Nov 6) to stabilize schema cutover.\n• Keep legacy cluster warm for 14-day instant rollback; decommission Nov 30."),
    ]
    for i, (st, dates, bullets) in enumerate(steps):
        x = 0.7 * inch + i * 4.08 * inch
        c.setFillColor(colors.HexColor("#F8FAFC"))
        c.setStrokeColor(colors.HexColor("#CBD5E1"))
        c.roundRect(x, 1.8 * inch, 3.78 * inch, 3.75 * inch, 6, fill=1, stroke=1)
        draw_wrapped_text(c, st, x + 0.22 * inch, 5.3 * inch, 3.35 * inch, "Helvetica-Bold", 13, 16, colors.HexColor("#1B365D"))
        draw_wrapped_text(c, dates, x + 0.22 * inch, 4.95 * inch, 3.35 * inch, "Helvetica-Bold", 10.5, 14, colors.HexColor("#2563EB"))
        draw_wrapped_text(c, bullets.replace("\n", "<br/><br/>"), x + 0.22 * inch, 4.45 * inch, 3.35 * inch, "Helvetica", 10.5, 15, colors.HexColor("#334155"))
    c.showPage()

    # Slide 5: Intellectual Honesty — Risks, Trade-Offs & Mitigations
    hdr(
        "4. Risks & Trade-Offs",
        "Three execution risks—feature freeze friction, Finance KPI parity, and vendor lock-in—have explicit owners.",
        5
    )
    risk_tbl = Table([
        ["Risk", "Impact if Unmitigated", "Mitigation & Owner"],
        ["3-week Oct feature freeze\ndelays Q4 merchandising asks", "Medium — slows 2 planned\npromo dashboards", "Pre-build holiday promo tables in Sep;\nMerchandising VP (M. Chen) signed off."],
        ["Row-level metric drift during\nFinance close reconciliation", "High — blocks Q3 audit\nsign-off", "30-day dual-run automated diff (<0.01% tol.);\nFinance Controller (R. Patel) gates cutover."],
        ["Managed vendor egress fees\nif we switch clouds later", "Low–Med — $180K switching\ncost in Year 3+", "Store all tables in open Apache Iceberg format\nin our own S3 bucket (Platform Eng — A. Diaz)."],
    ], colWidths=[3.0 * inch, 3.0 * inch, 5.9 * inch])
    risk_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1B365D")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ("FONTSIZE", (0, 0), (-1, -1), 10.5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 11),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 11),
    ]))
    risk_tbl.wrapOn(c, 12 * inch, 4.5 * inch)
    risk_tbl.drawOn(c, 0.7 * inch, 2.3 * inch)
    c.showPage()

    # Slide 6: Decision & Immediate Owners (Who / What / When)
    hdr(
        "5. Decision & Next Steps",
        "Approving $620K by May 15 unlocks immediate archival relief and keeps Nov 15 cutover on schedule.",
        6
    )
    next_tbl = Table([
        ["Action", "Owner", "Due Date", "Success Criterion"],
        ["Approve $620K CapEx/migration budget", "CFO & VP Engineering", "May 15, 2026", "Signed budget allocation"],
        ["Execute 2022–2023 log archival to S3", "A. Diaz (Data Platform)", "Jun 1, 2026", "Cluster utilization drops <78%"],
        ["Sign lakehouse vendor order form", "Procurement & A. Diaz", "Jun 10, 2026", "24-month committed discount locked"],
        ["Go/No-Go gate on Finance parity diff", "R. Patel (Finance) & A. Diaz", "Oct 12, 2026", "<0.01% variance across 24 KPIs"],
    ], colWidths=[4.2 * inch, 2.6 * inch, 1.8 * inch, 3.3 * inch])
    next_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1B365D")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ("FONTSIZE", (0, 0), (-1, -1), 10.5),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    next_tbl.wrapOn(c, 12 * inch, 4.5 * inch)
    next_tbl.drawOn(c, 0.7 * inch, 2.8 * inch)
    c.showPage()
    c.save()
    return path


# =============================================================================
# POSITIVE EXAMPLE 2: SHARP AMAZON-STYLE MEMO / PR-FAQ (AI Support Copilot)
# =============================================================================

def build_sharp_memo_ai_support_copilot():
    """A/B counterpart to Slop #2: Amazon 6-pager / PR-FAQ clear writing discipline.
    BLUF ask on line 1, data over adjectives, zero weasel words, <22-word avg sentences,
    first-use acronym expansion, clean chart, and pre-emptive Internal FAQ."""
    path = os.path.join(SHARP_DIR, "02_sharp_memo_ai_support_copilot.pdf")
    doc = SimpleDocTemplate(path, pagesize=letter, leftMargin=0.8 * inch, rightMargin=0.8 * inch,
                            topMargin=0.75 * inch, bottomMargin=0.75 * inch)
    styles = getSampleStyleSheet()
    title_s = ParagraphStyle("t", parent=styles["Title"], fontSize=16.5, alignment=TA_LEFT, textColor=colors.HexColor("#0F172A"), spaceAfter=4)
    meta_s = ParagraphStyle("m", parent=styles["Normal"], fontSize=9.2, textColor=colors.HexColor("#475569"), spaceAfter=10)
    h2_s = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=11.8, spaceBefore=12, spaceAfter=5, textColor=colors.HexColor("#1B365D"))
    body_s = ParagraphStyle("b", parent=styles["BodyText"], fontSize=10, leading=14.2, spaceAfter=8, textColor=colors.HexColor("#1E293B"))
    box_s = ParagraphStyle("box", parent=body_s, backColor=colors.HexColor("#EFF6FF"), borderPadding=8, spaceAfter=10)
    faq_q = ParagraphStyle("fq", parent=body_s, fontName="Helvetica-Bold", spaceBefore=6, spaceAfter=2, textColor=colors.HexColor("#0F172A"))

    chart_buf = chart_sharp_handle_time()

    story = [
        Paragraph("Decision Memo: 10-Week Pilot for Tier-1 Customer Support Copilot", title_s),
        Paragraph("<b>To:</b> VP Operations, CFO, VP Engineering &nbsp;|&nbsp; <b>From:</b> Support Platform Lead &nbsp;|&nbsp; <b>Date:</b> May 8, 2026", meta_s),
        HRFlowable(width="100%", color=colors.HexColor("#CBD5E1")),
        Spacer(1, 8),

        Paragraph(
            "<b>Decision Needed by May 22:</b> Approve $480K and 2 temporary Machine Learning (ML) platform engineers for a "
            "10-week pilot (Jun 22 – Aug 30) of an AI drafting copilot capped at 15% of Tier-1 tickets (21,000 tickets/month). "
            "We will hold a strict Go/No-Go review on Aug 30 based on three measurable gates: handle time, accuracy, and customer satisfaction.",
            box_s
        ),

        Paragraph("1. Context: Tier-1 Handle Time Rose 42% in 12 Months, Adding $1.8M in Annual BPO Spend", h2_s),
        Paragraph(
            "Our Tier-1 support team handles 142,000 customer tickets per month across billing, returns, and account access. "
            "Between Q1 2025 and Q1 2026, median Average Handle Time (AHT) climbed from 6.4 minutes to 9.1 minutes, breaching our "
            "6.5-minute Service Level Agreement (SLA) for three straight quarters. To absorb this backlog, we increased Business Process "
            "Outsourcing (BPO) contractor hours by 28%, adding $1.8M in annualized cost.",
            body_s
        ),
        Paragraph(
            "Time-motion audits of 600 tickets in March 2026 traced 61% of the increase to one root cause: agents spend an average of "
            "3.8 minutes searching across 1,400 fragmented Knowledge Base (KB) articles after four product-pricing updates in 2025. "
            "Customer Satisfaction (CSAT) fell from 88.2% to 82.4% over the same period.",
            body_s
        ),
        Image(chart_buf, width=5.4 * inch, height=2.55 * inch),
        Spacer(1, 6),

        Paragraph("2. Proposal: Human-in-the-Loop Copilot Using Retrieval-Augmented Generation (RAG)", h2_s),
        Paragraph(
            "We propose deploying a human-in-the-loop drafting assistant inside Zendesk for 45 Tier-1 agents (15% of queue volume). "
            "The copilot uses Retrieval-Augmented Generation (RAG) indexed strictly on our top 180 verified billing and returns policies. "
            "Every draft requires explicit agent review and shows clickable policy citations; the model never sends replies autonomously.",
            body_s
        ),
        Paragraph(
            "Between May 25 and June 19 (4 weeks), we will complete a System and Organization Controls 2 (SOC2) vendor security review "
            "with Legal and strip Personally Identifiable Information (PII) via our existing gateway proxy so the 10-week pilot launches "
            "on June 22 and completes Aug 30. Two ML platform engineers (loaned from Search Infra for 14 weeks total) will build the "
            "retrieval index and evaluation harness; zero permanent headcount is requested for the pilot.",
            body_s
        ),

        Paragraph("3. Pilot Economics and Hard Go/No-Go Thresholds (Aug 30 Review)", h2_s),
        Table([
            ["Metric", "Q1 '26 Baseline", "Aug 30 Pilot Gate", "Full-Rollout Annual Impact"],
            ["Median Tier-1 AHT", "9.1 min", "<= 7.3 min (-20%)", "$1.45M/yr BPO cost reduction"],
            ["Policy Accuracy (n=500 QA)", "96.2%", ">= 96.5% (no regression)", "Zero refund-leakage increase"],
            ["Tier-1 CSAT", "82.4%", ">= 85.0% (+2.6 pts)", "Recovers half of 2025 drop"],
            ["Total Investment", "—", "$480K pilot + $185K rollout", "$665K total = 5.5 mo payback"],
        ], colWidths=[1.55 * inch, 1.05 * inch, 2.25 * inch, 1.95 * inch], style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1B365D")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
            ("FONTSIZE", (0, 0), (-1, -1), 8.6),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ])),
        Spacer(1, 8),

        Paragraph("4. Pre-Emptive Internal FAQ (Risks, Trade-Offs & Alternatives)", h2_s),
        Paragraph("Q1: Why not just clean up the Knowledge Base instead of buying an AI tool?", faq_q),
        Paragraph(
            "We already archived 420 outdated articles in Q4 2025, which cut AHT by only 0.3 minutes. The remaining 180 active policies "
            "have 14 regional exceptions each, so keyword search still forces agents to open 4–6 tabs per ticket. Cleaning the KB is "
            "necessary—and feeds our RAG index—but insufficient alone.",
            body_s
        ),
        Paragraph("Q2: What happens if the copilot hallucinates a refund exception and costs us revenue?", faq_q),
        Paragraph(
            "First, the copilot is restricted to drafting—agents must click 'Send' and verify highlighted dollar amounts. Second, Quality "
            "Assurance (QA) will audit 500 pilot tickets per month (double our normal rate). If unauthorized refund error rates exceed "
            "0.4% (vs. 0.3% human baseline), we halt the pilot immediately.",
            body_s
        ),
        Paragraph("Q3: Does reducing BPO hours trigger minimum-commitment penalties?", faq_q),
        Paragraph(
            "No during the pilot, and no at full rollout if timed to our Q4 contract renewal. Our current BPO agreement (Apex Support) "
            "allows a 25% volume flex down with 60 days' notice starting Nov 1, 2026. Notice must be issued by Sep 1, which is why our "
            "Aug 30 Go/No-Go gate is critical.",
            body_s
        ),
        Paragraph("Q4: What is the exact fallback if the Aug 30 gate fails?", faq_q),
        Paragraph(
            "The vendor contract includes a 90-day pilot break clause with zero termination fee. The 2 loaned ML engineers return to "
            "Search Infra on Sep 1, and we retain the cleaned 180-article policy taxonomy regardless of outcome.",
            body_s
        ),
    ]
    doc.build(story)
    return path


# =============================================================================
# POSITIVE EXAMPLE 3: SHARP CROSS-ORG PARTNER DECK (Legacy Auth API v2 Sunset)
# =============================================================================

def build_sharp_deck_cross_org():
    """A/B counterpart to Slop #3: Tailored for 'Colleague in Another Division/Org'.
    Immediate partner impact on Slide 1, 100% acronym expansion, clear ownership, reconciled Nov 30 date."""
    path = os.path.join(SHARP_DIR, "03_sharp_deck_cross_org_api_deprecation.pdf")
    c = canvas.Canvas(path, pagesize=(SLIDE_W, SLIDE_H))

    def hdr(kicker, title, num):
        c.setFillColor(colors.HexColor("#0F766E"))
        c.setFont("Helvetica-Bold", 9.5)
        c.drawString(0.7 * inch, SLIDE_H - 0.5 * inch, kicker.upper())
        draw_wrapped_text(
            c, title, 0.7 * inch, SLIDE_H - 0.65 * inch, SLIDE_W - 1.4 * inch,
            "Helvetica-Bold", 19, 24, colors.HexColor("#0F172A")
        )
        c.setStrokeColor(colors.HexColor("#E2E8F0"))
        c.line(0.7 * inch, SLIDE_H - 1.38 * inch, SLIDE_W - 0.7 * inch, SLIDE_H - 1.38 * inch)
        c.setFillColor(colors.HexColor("#64748B"))
        c.setFont("Helvetica", 8.5)
        c.drawString(0.7 * inch, 0.35 * inch, "Core Platform → Payments Division Partner Brief | Auth API v2 Sunset")
        c.drawRightString(SLIDE_W - 0.7 * inch, 0.35 * inch, f"{num} / 5")

    # Slide 1: Immediate Partner Relevance, Plain English, Exact Ask & Deadline
    hdr(
        "Partner Action Brief — Payments Division",
        "Payments must migrate 3 backend services off Auth API v2 by Nov 30, 2026 to avoid checkout auth failures.",
        1
    )
    c.setFillColor(colors.HexColor("#F0FDFA"))
    c.setStrokeColor(colors.HexColor("#99F6E4"))
    c.roundRect(0.7 * inch, 4.45 * inch, 11.9 * inch, 1.45 * inch, 6, fill=1, stroke=1)
    draw_wrapped_text(
        c,
        "<b>Why You Are Seeing This:</b> Core Platform is retiring Legacy Authentication API v2 (our old internal service-to-service login bridge) "
        "on <b>Nov 30, 2026</b> to comply with Payment Card Industry (PCI) 2027 certificate-rotation rules.<br/><br/>"
        "<b>What We Need From Payments Eng Lead by June 15:</b> Confirm a Directly Responsible Individual (DRI) for the 3 affected services (~2 engineer-weeks total effort).",
        0.9 * inch, 5.7 * inch, 11.5 * inch, font_size=11.5, leading=16, color=colors.HexColor("#134E4A")
    )

    cards = [
        ("Affected Payments Services", "3 services (of 19 total)", "1. payments-ledger-api\n2. settlement-batch-worker\n3. refund-webhook-relay"),
        ("Estimated Payments Effort", "~2 engineer-weeks", "Drop-in SDK swap + 1 config PR per service. Zero database or customer-facing API changes."),
        ("Hard Cutover Deadline", "Nov 30, 2026", "Legacy API v2 returns HTTP 401 after Nov 30. Payments gets the final migration wave after Commerce & Fulfillment."),
    ]
    for i, (h, big, txt) in enumerate(cards):
        x = 0.7 * inch + i * 4.08 * inch
        c.setFillColor(colors.white)
        c.setStrokeColor(colors.HexColor("#CBD5E1"))
        c.roundRect(x, 1.3 * inch, 3.78 * inch, 2.8 * inch, 6, fill=1, stroke=1)
        draw_wrapped_text(c, h, x + 0.22 * inch, 3.88 * inch, 3.35 * inch, "Helvetica-Bold", 10.5, 14, colors.HexColor("#0F766E"))
        draw_wrapped_text(c, big, x + 0.22 * inch, 3.55 * inch, 3.35 * inch, "Helvetica-Bold", 15, 19, colors.HexColor("#0F172A"))
        draw_wrapped_text(c, txt.replace("\n", "<br/>"), x + 0.22 * inch, 2.95 * inch, 3.35 * inch, "Helvetica", 10.8, 15.5, colors.HexColor("#334155"))
    c.showPage()

    # Slide 2: Plain-English Explanation of What Changes (Zero Jargon!)
    hdr(
        "What Is Changing (Plain English)",
        "The new Auth v3 SDK replaces static 90-day API keys with automatic 15-minute rotating certificates.",
        2
    )
    comp = Table([
        ["Dimension", "Legacy Auth API v2 (Retiring)", "New Auth v3 SDK (Gatekeeper)", "Impact on Payments Code"],
        ["How services\nauthenticate", "Static shared secret key\nrotated manually every 90 days", "Short-lived Mutual TLS (mTLS)\ncertificates auto-rotated every 15 min", "No manual secret rotation\ntickets anymore"],
        ["Integration work", "Custom HTTP header signing", "Install auth-v3-sdk (>= v3.2) +\nadd 8 lines in service YAML", "~3–4 days per service\nincl. staging tests"],
        ["Latency &\nReliability", "Central auth lookup adds\n18ms p99 latency", "Local verification drops auth\noverhead to <2ms p99", "16ms faster internal\ncheckout calls"],
        ["Failure / Rollback", "—", "Dual-auth flag accepts both\nv2 & v3 during rollout", "Instant 1-flag rollback\nuntil Nov 29"],
    ], colWidths=[1.8 * inch, 3.2 * inch, 3.8 * inch, 3.1 * inch])
    comp.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    comp.wrapOn(c, 12 * inch, 4.5 * inch)
    comp.drawOn(c, 0.7 * inch, 2.0 * inch)
    c.showPage()

    # Slide 3: Exact Inventory of Payments Endpoints (Immediately Actionable)
    hdr(
        "Payments Service Inventory",
        "Only 3 Payments services call Auth API v2; Core Platform already opened draft starter PRs for each.",
        3
    )
    inv = Table([
        ["Payments Service", "Current v2 Endpoint Called", "Daily Calls", "Draft PR Ready?", "Est. Effort"],
        ["payments-ledger-api", "POST /v2/internal/token", "1.4M / day", "Yes — PR #4821", "4 eng-days"],
        ["settlement-batch-worker", "POST /v2/internal/token", "42K / day", "Yes — PR #1109", "3 eng-days"],
        ["refund-webhook-relay", "GET /v2/internal/verify", "180K / day", "Yes — PR #732", "3 eng-days"],
    ], colWidths=[2.7 * inch, 2.8 * inch, 1.8 * inch, 2.4 * inch, 2.2 * inch])
    inv.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F766E")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F0FDFA")]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ("FONTSIZE", (0, 0), (-1, -1), 11),
        ("TOPPADDING", (0, 0), (-1, -1), 11),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 11),
    ]))
    inv.wrapOn(c, 12 * inch, 4 * inch)
    inv.drawOn(c, 0.7 * inch, 3.4 * inch)
    draw_wrapped_text(
        c,
        "<b>Verified via production gateway logs (Apr 1–30, 2026):</b> The other 16 Payments services are already on Auth v3 or use public OAuth and require zero work.",
        0.7 * inch, 2.75 * inch, 11.8 * inch, font_size=11, leading=16, color=colors.HexColor("#334155")
    )
    c.showPage()

    # Slide 4: Reconciled Wave Schedule (Zero Contradictions!)
    hdr(
        "Cross-Division Cutover Schedule",
        "Payments migrates in Wave 3 (Oct–Nov), giving you 4 months of runway and lessons from Waves 1–2.",
        4
    )
    sched = Table([
        ["Wave", "Division", "Staging Cutover", "Prod Cutover", "Platform Support DRI"],
        ["Wave 1", "Commerce (5 services)", "Aug 15, 2026", "Sep 15, 2026", "S. Gupta (Core Auth)"],
        ["Wave 2", "Fulfillment (4 services)", "Sep 15, 2026", "Oct 15, 2026", "S. Gupta (Core Auth)"],
        ["Wave 3", "Payments (3 services)", "Oct 30, 2026", "Nov 20, 2026", "L. Kim (Dedicated Liaison)"],
        ["Sunset", "Legacy Auth v2 Shutdown", "—", "Nov 30, 2026", "All waves complete + 10-day buffer"],
    ], colWidths=[1.3 * inch, 2.9 * inch, 2.2 * inch, 2.2 * inch, 3.3 * inch])
    sched.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BACKGROUND", (0, 3), (-1, 3), colors.HexColor("#CCFBF1")),
        ("FONTNAME", (0, 3), (-1, 3), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ("FONTSIZE", (0, 0), (-1, -1), 10.5),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    sched.wrapOn(c, 12 * inch, 4 * inch)
    sched.drawOn(c, 0.7 * inch, 2.75 * inch)
    c.showPage()

    # Slide 5: Clear Support Contract & Immediate Next Steps
    hdr(
        "Support & Next Steps",
        "Confirm your Payments DRI by June 15; Core Platform provides office hours and live pairing.",
        5
    )
    ns = Table([
        ["Milestone", "Owner", "Date", "How Core Platform Helps"],
        ["Assign Payments DRI for 3 PRs", "Payments Eng Lead", "Jun 15, 2026", "30-min kickoff walkthrough with L. Kim"],
        ["Merge & test dual-auth in staging", "Payments DRI + L. Kim", "Oct 30, 2026", "Automated load test + #auth-v3-migration Slack"],
        ["Switch prod traffic to Auth v3", "Payments DRI", "Nov 20, 2026", "Live war-room monitoring + 1-flag rollback"],
        ["Legacy Auth v2 decommissioned", "Core Platform (S. Gupta)", "Nov 30, 2026", "Zero-traffic verification 48h prior"],
    ], colWidths=[3.3 * inch, 2.4 * inch, 1.8 * inch, 4.4 * inch])
    ns.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F766E")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ("FONTSIZE", (0, 0), (-1, -1), 10.5),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    ns.wrapOn(c, 12 * inch, 4 * inch)
    ns.drawOn(c, 0.7 * inch, 2.85 * inch)
    c.showPage()
    c.save()
    return path


if __name__ == "__main__":
    outputs = [
        build_slop_deck_cloud_migration(),
        build_slop_memo_ai_support_copilot(),
        build_slop_deck_cross_org(),
        build_sharp_deck_cloud_migration(),
        build_sharp_memo_ai_support_copilot(),
        build_sharp_deck_cross_org(),
    ]
    for p in outputs:
        print(f"Generated: {p} ({os.path.getsize(p):,} bytes)")
