# Slop Gate — Benchmark & Calibration Corpus

This catalog pairs **renowned real-world exemplars** of sharp writing and presentations with **6 generated A/B test PDFs** (`examples/sharp/` vs. `examples/slop/`) designed to test and calibrate Gate 1's format detection, visual clutter telemetry, Ghost-Deck audit, Amazon clear-writing linters, logical consistency detector, and persona weighting.

---

## 1. Real-World Online Exemplars of Sharp Documents & Presentations

### Sharp Documents (Memos, PR/FAQs & Letters)

| Exemplar | Format | What Makes It Sharp | Principles Borrowed for Slop Gate |
| :--- | :--- | :--- | :--- |
| **Amazon Prime Pantry PR/FAQ (2013)** *(Wharton / Working Backwards breakdown)* | Narrative PR/FAQ | Starts from the customer outcome in plain English, then directly tackles brutal unit-economics and shipping-weight FAQs before writing code. | Pre-emptive Internal FAQ audit (economics, risks, constraints); zero marketing hype. |
| **Jeff Bezos 1997 & 2015 Shareholder Letters** *(Amazon Investor Relations)* | Executive Narrative | Crystal-clear tenets upfront, concrete operating metrics instead of vague adjectives, explicit acknowledgment of risks and failures. | Data over adjectives; intellectual honesty; explicit decision frameworks. |
| **Stripe — "Ending Bitcoin Support" (Jan 2018)** *(Stripe Blog)* | Decision Memo | Crisp, prose-driven trade-off memo citing specific friction metrics (confirmation delays, fees, volatility) with zero corporate fluff. | Concrete evidence per claim; clear "So What?" and clean decision rationale. |
| **Intercom Strategy & Product Memos** *(Intercom Blog)* | Strategy Memo | Uses full prose paragraphs to force logical transitions and tackles counterarguments head-on before pitching a roadmap. | Logical consistency across sections; counterargument coverage. |

### Sharp Presentations (Executive & Technical Decks)

| Exemplar | Format | What Makes It Sharp | Principles Borrowed for Slop Gate |
| :--- | :--- | :--- | :--- |
| **McKinsey USPS Future Business Model** *(Public Sector PDF)* | Executive Consulting Deck | Full-sentence **Action Titles** (Diagnostic → Analytical → Prescriptive) where reading only the titles gives the entire narrative arc; MECE pillar breakdown. | Flagship **Ghost-Deck Horizontal Logic Test**; pragmatic McKinsey Pyramid audit. |
| **Penn State Assertion-Evidence Slides** *(Michael Alley — `writing.engr.psu.edu/slides.html`)* | Technical Presentation | Replaces passive topic headers + bullet walls with a 1–2 line takeaway assertion headline paired with direct visual proof. | Assertion-Evidence visual-to-claim pairing; slide text-bandwidth limits. |
| **Airbnb Seed Deck (2008)** | Pitch Deck | Ruthless 10-slide simplicity; 1-line value prop (*"Book rooms with locals, rather than hotels"*); bottom-up TAM math instead of top-down fluff. | Cold-start clarity on Slide 1; anchored bottom-up numbers vs. hollow precision. |
| **Sequoia 10-Slide Structure** | Strategy / Pitch Deck | Enforces deliberate narrative sequence (Purpose → Problem → Solution → Why Now → Evidence → Plan) so the deck reads as a logical argument, not a brochure. | Narrative progression & SCQA cold-start framing. |

---

## 2. Generated Calibration PDFs (`examples/`)

We created **3 matched A/B pairs** covering the exact same underlying business scenarios—one **AI Slop** version with deliberate failure modes, and one **Sharp** counterpart modeled on the exemplars above.

### Pair 1 — Executive Presentation for Leadership (`Slide Deck` | `Leadership`)
- **Negative (Slop):** [01_slop_deck_cloud_migration.pdf](file:///Users/Krishna_KUMAR/AGFolder/slop-gate/examples/slop/01_slop_deck_cloud_migration.pdf) *(6 slides)*
  - **Planted Failure Modes:**
    - Passive topic titles on every slide (*"Overview"*, *"Strategic Architecture"*, *"Financial Projections"*, *"Next Steps"*) → fails Ghost-Deck test.
    - No cold-start context for Project Helios and no decision ask on Slides 1–2.
    - High visual clutter: Slide 3 has 8 dense bullets + a 12-box spaghetti architecture diagram; Slide 4 has a garish 8-slice shadowed pie chart with a distant legend + truncated y-axis bar chart.
    - **Critical Logical & Numerical Contradictions:** Slide 2 claims **\$2.4M savings starting Q3 2026**, while Slide 4's table totals **\$1.10M savings** and Slide 5's roadmap puts cutover in **Q1 2027**.
    - **Support-Relation Contradiction:** Slide 4's bar chart shows flat query volume (410K → 425K), contradicting the prose claim of *"exponential query demand acceleration."*
    - Heavy Amazon weasel words (*significantly, massively, nearly all, world-class, seamless*) and unexpanded acronyms (`DWH`, `CDC`, `E2E`, `FinOps`, `RBAC/ABAC`).
    - Zero risks or trade-offs.
  - **Expected Gate 1 Verdict:** `HIGH_SLOP_BLOCKED` (< 50, multiple Critical Blockers).
- **Positive (Sharp):** [01_sharp_deck_cloud_migration.pdf](file:///Users/Krishna_KUMAR/AGFolder/slop-gate/examples/sharp/01_sharp_deck_cloud_migration.pdf) *(6 slides)*
  - **Sharp Traits:** Pragmatic McKinsey Pyramid structure, 100% Action Titles passing the Ghost-Deck test, Slide 1 SCQA context reminder + explicit Ask (*Approve \$620K by May 15*), clean Cleveland-McGill charts with direct labels, 100% reconciled numbers (**\$1.15M/yr savings, 6.5-month payback, Nov 15 cutover**), explicit risks & owners slide, clear reason Option B was ruled out.
  - **Expected Gate 1 Verdict:** `CLEARED` (≥ 85, 0 Blockers).

---

### Pair 2 — Narrative Memo for Leadership (`Narrative Memo` | `Leadership` | `Decide/Approve`)
- **Negative (Slop):** [02_slop_memo_ai_support_copilot.pdf](file:///Users/Krishna_KUMAR/AGFolder/slop-gate/examples/slop/02_slop_memo_ai_support_copilot.pdf) *(2 dense pages)*
  - **Planted Failure Modes:**
    - Wall-of-text justified prose; long sentences averaging >35 words; corporate fluff (*"due to the fact that"*, *"in order to"*).
    - **Buried Ask:** The actual **\$480K funding + 2 ML engineers** ask is buried on the final page.
    - **Internal Logical Contradiction:** Page 1 promises *"rapid, seamless deployment using existing infrastructure with zero incremental headcount impact"*, while Page 1–2 quietly requires **hiring 2 ML engineers** and a **6-month SOC2 audit**.
    - **Hollow Precision & Weasel Words:** *"up to a 40% improvement in overall efficiency"* (no baseline/timeframe), *"dramatically"*, *"nearly all"*, *"vastly"*, *"massively"*.
    - Unexpanded acronyms (`AHT`, `FCR`, `KB`, `BPO`, `RAG`, `CSAT`, `TTR`, `PII`) and zero pre-emptive FAQ / risks.
  - **Expected Gate 1 Verdict:** `NEEDS_REWORK` (Critical contradictions + buried ask).
- **Positive (Sharp):** [02_sharp_memo_ai_support_copilot.pdf](file:///Users/Krishna_KUMAR/AGFolder/slop-gate/examples/sharp/02_sharp_memo_ai_support_copilot.pdf) *(2 clean pages)*
  - **Sharp Traits:** Amazon PR/FAQ & 6-Pager discipline; Decision Ask in a highlighted box at the top of Page 1; reconciled timeline (May 22 approval → 4-week SOC2 review → 10-week pilot Jun 22–Aug 30) and reconciled payback (`\$480K` pilot + `\$185K` rollout = `\$665K` / `\$1.45M/yr` = `5.5 mo`); accurate acronym expansions (`System and Organization Controls 2 (SOC2)`); clean trend chart; dedicated **Pre-Emptive Internal FAQ**.
  - **Expected Gate 1 Verdict:** `READY` (`0 Critical` issues).

---

### Pair 3 — Subtle Cross-Org Deck (`Slide Deck` | `Colleague in Another Division/Org` | `Decide/Approve`)
- **Negative (Slop):** [03_slop_deck_cross_org_api_deprecation.pdf](file:///Users/Krishna_KUMAR/AGFolder/slop-gate/examples/slop/03_slop_deck_cross_org_api_deprecation.pdf) *(5 slides)*
  - **Why This Test Matters:** Looks **visually clean and uncluttered**—testing whether Gate 1 catches *cognitive & context overload* even when visual clutter is low!
  - **Planted Failure Modes:**
    - Fails Cross-Org persona cold-start: Payments Division isn't even mentioned until Slide 4; Slide 3 wastes an entire slide on internal control-plane jargon (`SPIFFE`, `X.509 SVID`, `Envoy SDS`, `UDS`, `PDP`, `WASM OPA`, `MTLS-rotator`) failing the "So What?" test.
    - **Deadline Contradiction:** Slide 2 says *"full Legacy Auth v2 sunset on October 15, 2026"*, while Slide 5's table sets Payments cutover to **Nov 30, 2026**.
    - Passive topic titles and vague ownership (*"Teams should coordinate seamlessly"*).
  - **Expected Gate 1 Verdict:** `FIX_CRITICAL_ISSUES` or `NEEDS_REWORK` (especially under **Colleague in Another Division/Org** persona).
- **Positive (Sharp):** [03_sharp_deck_cross_org_api_deprecation.pdf](file:///Users/Krishna_KUMAR/AGFolder/slop-gate/examples/sharp/03_sharp_deck_cross_org_api_deprecation.pdf) *(5 slides)*
  - **Sharp Traits:** Slide 1 immediately tells Payments Eng Lead what breaks, which 3 services are affected, estimated effort (~2 eng-weeks), hard deadline (Nov 30), and exact action needed by June 15. Plain-English translation of technical changes, 100% acronym expansion, starter PR numbers ready, reconciled Wave 1–3 timeline, and named DRIs.
  - **Expected Gate 1 Verdict:** `READY` (`0 Critical` issues).

---

## 3. Hard / Middle-Ground Calibration PDFs (`examples/hard/`)

Added following [pm_review_iter1_2026-11-24.md](file:///Users/Krishna_KUMAR/.gemini/antigravity/brain/92e0388f-8852-42ec-aa1a-ce944ee55f3b/pm_review_iter1_2026-11-24.md) to stress-test Gate 1 beyond "easy mode" polarized examples:

| File | Format / Purpose / Persona | Test Objective | Expected Gate 1 Verdict |
| :--- | :--- | :--- | :--- |
| [01_hard_smooth_2026_ai_slop.pdf](file:///Users/Krishna_KUMAR/AGFolder/slop-gate/examples/hard/01_hard_smooth_2026_ai_slop.pdf) *(5 slides)* | `Slide Deck` · `Decide/Approve` · `Leadership` | **Hard Negative (Zero Cliché Words):** Modern minimalist design, crisp bar chart, zero buzzwords (*synergy/holistic/seamlessly* absent)—yet hides a **cherry-picked seasonal baseline** (Feb trough vs. Nov peak = "+39% momentum"), **generic interchangeable strategy**, **zero costs/headcount/trade-offs**, and **no clear Decision Ask**. | `FIX_CRITICAL_ISSUES` or `NEEDS_REWORK` (flags Missing Ask + Unsupported Seasonal Leap + Hollow Strategy). |
| [02_hard_messy_human_genius_rfc.pdf](file:///Users/Krishna_KUMAR/AGFolder/slop-gate/examples/hard/02_hard_messy_human_genius_rfc.pdf) *(2 pages)* | `Narrative Memo` · `Decide/Approve` · `Leadership` | **False-Positive Trap (Must PASS):** Dense, plain Principal Engineer RFC with passive headings (*"Latency Analysis"*, *"Failure Modes"*), tight tables, and unexpanded domain acronyms (`p99`, `WAL`, `gRPC`, `CRC32`, `LSM`)—but airtight math, real load-test benchmarks, explicit May 18 Ask, and ruthless trade-offs. | **`READY`** (`0 Critical` issues; Polish tips only, NEVER blocked!). |
| [03_hard_inform_only_sev1_postmortem.pdf](file:///Users/Krishna_KUMAR/AGFolder/slop-gate/examples/hard/03_hard_inform_only_sev1_postmortem.pdf) *(2 pages)* | `Narrative Memo` · `Inform/Align` · `Leadership` | **Purpose Selector Test (Must PASS):** Crisp, blameless SEV-1 postmortem with exact timeline, root cause, customer impact, and funded corrective actions—**zero funding/approval Ask**. Verifies `Inform/Align` never triggers a false "Missing Ask" blocker. | **`READY`** (`0 Critical` issues). |
| [04_hard_15p_exec_deck_appendix_contradiction.pdf](file:///Users/Krishna_KUMAR/AGFolder/slop-gate/examples/hard/04_hard_15p_exec_deck_appendix_contradiction.pdf) *(15 slides)* | `Slide Deck` · `Decide/Approve` · `Leadership` | **Long-Context Contradiction Test:** Mostly sharp 15-slide Board QBR & FY27 plan hiding **2 subtle executive-grade contradictions**: (1) Slide 2 claims `\$4.2M Net New ARR` & `118% NRR` vs. Slide 14 Appendix Cohort Table showing `\$3.1M` true organic Net New ARR & `109% NRR` (`\$1.1M` was renewal pull-forward); (2) Slide 6 claims 8 H1 AEs add *"zero incremental OpEx"* vs. Slide 13 Finance Bridge showing `+\$1.44M` unbudgeted Sales headcount variance. | **`FIX_CRITICAL_ISSUES`** (catches both long-range contradictions accurately!). |

