# Slop Gate — Project Context & Resume Handoff

> **Last Saved:** `2026-11-24 15:28 (UTC+8)`  
> **Status:** **Phase 1 + Phase 2 (Full Dual-Gate v1) Built & Verified** (Gate 1 Pre-Flight + Gate 2 Meeting Q&A Prep + Final Read-Through + Luminance-Adaptive `Reviewed by <Owner Name>` PDF Stamp + 10-PDF Calibration Harness). Ready for live Gemini model benchmarking & interactive browser testing.

---

## 1. Core Product Vision & Locked Decisions

**Goal:** Prevent creators from sending AI slop to busy readers by validating:
1. **Pre-Flight Check (Gate 1):** Document is sharp, concise, logically consistent, and low-overload for its format, purpose, and target reader.
2. **Creator Ownership & Accountability (Gate 2 + Final Read-Through):** Creator proves genuine understanding via fewer, ultra-relevant questions (typed in own words, no copy-paste) + a **Known Limitations & v2 Improvements** reflection, then completes a **Final Page-by-Page Read-Through** to earn the **`✓ Reviewed by <Owner Name>`** stamp.

### Key Finalized Design Decisions
- **Owner Accountability Stamp (No "Slop" Branding on Export):** Stamps a subtle, luminance-adaptive vector pill (**`✓ Reviewed by <Owner Name>`**, frosted-paper on light corners, dark-glass on dark corners, consistent document-wide corner anchored below slide footers) + durable `/Info` xref metadata (`ReviewedBy`, `PreFlightStatus`, `DocumentFormat`, `DocumentPurpose`, `TargetPersona`, `VerifiedAt`) and `keywords`.
- **Format-First, Purpose-Aware, Persona-Calibrated:**
  - Format (auto-detected + confirmed): `Slide Deck` (pragmatic McKinsey Pyramid + Assertion-Evidence) vs. `Narrative Memo` (Amazon PR/FAQ & 6-Pager clear writing + ISO 24495).
  - Purpose: `Decide / Approve` | `Inform / Align` (hard-strips `MISSING_ASK`) | `Unblock / Escalate`.
  - Persona (Reverse Cohesion Effect): `Leadership` (default — doesn't nag standard eng/business acronyms) | `Colleague in Another Division / Org` | `Custom`.
- **Issue-Driven Verdicts (No 0–100 Score Caps, No Brittle CV Clutter Math):** `READY` / `FIX CRITICAL ISSUES` / `NEEDS REWORK`. Amazon linters (weasel words, >30-word sentences, local acronyms, dense slides) live in a collapsed, strictly non-blocking `Polish` drawer.
- **Pre-Critique 1-Sentence Intent Wait:** Always waits for the creator to submit their 1-sentence intended takeaway before revealing AI feedback (even if the backend finishes faster), preventing AI anchoring (Fernandes & Tankelevitch, 2026).
- **Non-Polish Triage Gate:** Creator cannot advance past Pre-Flight until every `Critical` and `Verify` issue is resolved via `Re-upload v2`, marked **`Intentional`** (requires a 1-line reason on `Critical`), or marked **`Ignore for now`**.
- **Final Page-by-Page Read-Through:** Mandatory full-page proofing pass before `Download Reviewed PDF` unlocks, protecting the sanctity of `✓ Reviewed by <Owner Name>`. Page-hash diffing preserves unchanged checkmarks across `v1 → v2` re-uploads.
- **Public-Safe Demo Posture:** Clear notice on upload dropzone (*only upload docs safe for ChatGPT/Gemini; no confidential enterprise files*); code & storage sit behind clean interfaces for enterprise self-hosting later.

---

## 2. What Is Built & Where Everything Lives

### Codebase (`/Users/Krishna_KUMAR/AGFolder/slop-gate/`)
- **Backend (`backend/app/`):**
  - `main.py` — FastAPI app, `lifespan` SQLite init + 15-min periodic TTL sweeper, static frontend serving.
  - `config.py` — Env/Pydantic settings (`GEMINI_API_KEY`, `LLM_MODEL_REASONING`, `LLM_MODEL_FAST`, limits).
  - `schemas/` — `document.py`, `gate1.py` (separate `Pass2LLMOutput` & `Gate1Report`), `stamp.py`.
  - `services/pdf_ingest.py` — PyMuPDF rendering (UI PNG + thumb + LLM JPEG `1280/1024px`), cover/memo heading extraction, 3-part page fingerprinting (`text_hash`, `embedded_img_hash`, `dhash_256` + quadrant dHashes), content-addressed `compute_revision_diff`.
  - `services/polish_linters.py` — Non-blocking Amazon & Reverse-Cohesion Polish linters.
  - `services/llm_provider.py` — Pluggable `LLMProvider` + `GeminiProvider` (`google-genai`, `max_output_tokens=8192`, `>15 MB` Files API fallback, jittered transient retries, `thoughts_tokens` tracking).
  - `services/gate1_engine.py` — Parallel Pass 1 (isolated Ghost-Deck, sole owner of `WEAK_STORYLINE`) + Pass 2 (multimodal audit), Post-LLM Grounding Validator, total `compute_verdict()`, and Local Demo Mode fallback when `GEMINI_API_KEY` is unset.
  - `services/gate2_engine.py` — High-relevance Meeting Q&A Prep (2–3 targeted hotspot questions + 1 Known Limitations reflection), page-fingerprint `v1 → v2` preservation with page-index remapping, smart verbatim-retype guard (`>=7` non-stopword tokens), Light/Encouraging grading, and Markdown Prep Sheet compiler.
  - `services/pdf_stamper.py` — `page.wrap_contents()`, document-wide preferred corner, luminance-adaptive vector pill, durable `/Info` xref keys (`PreFlightStatus=VERIFIED_FULL` when Gate 1 + Gate 2 + Read-Through all pass).
  - `services/session_store.py` — Async `aiosqlite` in `WAL` mode, revision-keyed tables (`sessions`, `revisions`, `gate1_runs`, `gate2_sessions`, `gate2_answers`, `readthrough_state`).
  - `services/sse_bus.py` — 2-step `EventSource` SSE bus with `Last-Event-ID` replay & 15s heartbeats.
  - `routers/` — `documents.py`, `gate1.py`, `gate2.py`, `stamp.py`.
- **Frontend (`frontend/`):**
  - Zero-build responsive SPA (`index.html`, `static/css/app.css`, `static/js/app.js`) served directly by FastAPI (note: `npm` is not installed on this machine; Python 3.12 + `uv` is in `.venv/`).
  - Includes Light/Dark theme, **⚙ Model & Key** modal (paste `GEMINI_API_KEY` per tab without restarting), 2-Column Triage Workspace + Auto Dual-Page Compare, 720px half-screen collapse, `Intentional`/`Ignore for now`, Final Read-Through, and live stamp preview.
- **Calibration Corpus (`examples/` — 10 PDFs):**
  - `examples/sharp/` (3 PDFs), `examples/slop/` (3 PDFs), `examples/hard/` (4 hard cases: Smooth 2026 Slop, Messy Human Genius RFC, Inform-Only SEV-1 Postmortem, 15-Slide Exec QBR w/ 2 appendix contradictions).
  - Catalog: `examples/BENCHMARK_CATALOG.md`.
- **Tests & Eval:**
  - `backend/tests/test_core.py` (`6/6` passing).
  - `eval/expected_cases.json` & `eval/run_benchmark.py` (deterministic contradiction matchers, `--runs K`, token/latency logging).

### Reference Artifacts (Conversation `92e0388f-8852-42ec-aa1a-ce944ee55f3b`)
Located in `/Users/Krishna_KUMAR/.gemini/antigravity/brain/92e0388f-8852-42ec-aa1a-ce944ee55f3b/`:
- `spec.md` (v5) — Product & Technical Spec
- `eng_design.md` (v1) — Engineering Design Document
- `gate2_ux_design.md` (v3) — Gate 2 High-Relevance Ownership UX Spec
- `msr_research_synthesis.md` — Advait Sarkar & Lev Tankelevitch (MSR Cambridge, 2023–2026) synthesis
- `pm_review_iter1_2026-11-24.md`, `ux_review_iter1_2026-11-24.md`, `eng_review_iter1_2026-11-24.md` — Principal reviews
- `prototype.html` — Interactive click-through prototype

---

## 3. Quick Commands on Resume

```bash
# Run tests
.venv/bin/pytest backend/tests -v

# Start Slop Gate locally (http://localhost:8000)
PYTHONPATH=backend .venv/bin/uvicorn app.main:app --reload --port 8000

# Benchmark live Gemini models across all 10 calibration PDFs
GEMINI_API_KEY=your_key .venv/bin/python eval/run_benchmark.py --model gemini-2.5-pro --runs 3
```

---

## 4. Exact Next Steps When You Return

1. **Live Model Calibration:** Run `eval/run_benchmark.py` with your `GEMINI_API_KEY` across candidate Gemini models (`gemini-2.5-pro`, `gemini-3.8-flash`, `gemini-4-neon`, etc.) to verify `10/10` verdicts, `>=90%` contradiction recall, and zero false-positive blocks on `hard_02_messy_rfc` & `hard_03_inform_postmortem`.
2. **Live UI Walkthrough:** Start `uvicorn`, open `http://localhost:8000`, and test uploading your own PDFs + re-uploading `v2` + downloading a stamped PDF.
3. **Build Phase 2 — Gate 2 (Meeting Q&A Prep):**
   - Backend: `gate2_engine.py` + `routers/gate2.py` generating **3–4 high-relevance doc-specific questions + 1 Known Limitations & v2 Improvements prompt**, smart verbatim-overlap check (ignoring numbers/proper nouns), Light/Encouraging LLM grading, and `gate2_answers` page-hash preservation across `v1 → v2`.
   - Frontend: Insert **Meeting Q&A Prep** cleanly between Pre-Flight Check and Final Read-Through (reusing the 2-column split with on-demand `Inspect Page N`, gentle 35% dim + sticky `Pin Slide`, smart paste guard allowing `<20` chars & internal cut/paste, and copyable **Meeting Q&A Prep Sheet** on Sign-Off).
   - Optional: Add Case #11 (adversarial visual + text prompt-injection PDF) to `eval/` and tune `eng_design.md` to v2.
