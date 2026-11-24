#!/usr/bin/env python3
"""Offline Calibration & Model Benchmark Harness for Slop Gate (Gate 1).

Runs all 10 Sharp / Slop / Hard PDFs across candidate Gemini models (or local demo mode),
scoring verdicts and deterministic contradiction matchers without circular LLM judging.

Usage:
  .venv/bin/python eval/run_benchmark.py --runs 1
  GEMINI_API_KEY=... .venv/bin/python eval/run_benchmark.py --model gemini-3.1-pro-preview --runs 3
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.schemas.gate1 import Gate1Report
from app.services.gate1_engine import execute_gate1
from app.services.pdf_ingest import ingest_pdf_sync


def match_contradiction(report: Gate1Report, spec: dict[str, object]) -> bool:
    req_pages = set(spec["required_pages"])  # type: ignore[arg-type]
    cats = set(spec["categories"])  # type: ignore[arg-type]
    sev = str(spec["severity"])
    groups: list[list[str]] = spec["token_groups"]  # type: ignore[assignment]

    for issue in report.issues:
        if issue.severity.value != sev:
            continue
        if issue.category.value not in cats:
            continue
        cited = set(issue.pages) | {e.page for e in issue.evidence}
        if not req_pages.issubset(cited):
            continue
        blob = " ".join([issue.title, issue.explanation, *(e.quote for e in issue.evidence)]).lower()
        if all(any(re.search(pat, blob, re.I) for pat in grp) for grp in groups):
            return True
    return False


async def run_all(cases_path: Path, model_reasoning: str | None, model_fast: str | None, runs: int) -> dict[str, object]:
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    results: list[dict[str, object]] = []
    verdict_passes = 0
    total_contradictions = 0
    matched_contradictions = 0

    for case in cases:
        pdf_path = REPO_ROOT / case["path"]
        pdf_bytes = pdf_path.read_bytes()
        case_runs: list[dict[str, object]] = []

        with tempfile.TemporaryDirectory(prefix=f"bench_{case['id']}_") as tmp:
            rev_dir = Path(tmp)
            ingested = ingest_pdf_sync(pdf_bytes, rev_dir)

            for r_idx in range(1, runs + 1):
                report = await execute_gate1(
                    run_id=f"{case['id']}_r{r_idx}",
                    session_id=f"bench_{case['id']}",
                    revision=1,
                    pages=ingested["pages"],  # type: ignore[arg-type]
                    revision_dir=rev_dir,
                    revision_diff=None,
                    doc_format=case["doc_format"],
                    doc_purpose=case["doc_purpose"],
                    target_persona=case["target_persona"],
                    ghost_deck_mode=ingested["ghost_deck_mode"],  # type: ignore[arg-type]
                    model_reasoning=model_reasoning,
                    model_fast=model_fast,
                )

                v_ok = report.verdict in case["allowed_verdicts"]
                c_matches = {
                    c["id"]: match_contradiction(report, c)
                    for c in case["expected_contradictions"]
                }
                case_runs.append(
                    {
                        "run": r_idx,
                        "verdict": report.verdict,
                        "verdict_pass": v_ok,
                        "mode": report.mode,
                        "model_used": report.model_used,
                        "latency_ms": report.latency_ms,
                        "pass1_ms": report.pass1_ms,
                        "pass2_ms": report.pass2_ms,
                        "usage": report.usage.model_dump(),
                        "critical_count": len([i for i in report.issues if i.severity.value == "critical"]),
                        "verify_count": len([i for i in report.issues if i.severity.value == "verify"]),
                        "invalid_citations_dropped": report.invalid_citations_dropped,
                        "contradiction_matches": c_matches,
                    }
                )

        unanimous_pass = all(r["verdict_pass"] for r in case_runs)
        if unanimous_pass:
            verdict_passes += 1

        for c in case["expected_contradictions"]:
            total_contradictions += 1
            if all(r["contradiction_matches"][c["id"]] for r in case_runs):
                matched_contradictions += 1

        results.append(
            {
                "id": case["id"],
                "allowed_verdicts": case["allowed_verdicts"],
                "unanimous_pass": unanimous_pass,
                "runs": case_runs,
            }
        )
        r0 = case_runs[0]
        status_icon = "PASS" if unanimous_pass else "FAIL"
        print(
            f"[{status_icon}] {case['id']:<26} verdict={r0['verdict']:<19} "
            f"crit={r0['critical_count']} ver={r0['verify_count']} "
            f"contradictions={r0['contradiction_matches']} ({r0['latency_ms']}ms)"
        )

    summary = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "runs_per_case": runs,
        "verdict_unanimous_pass": f"{verdict_passes}/{len(cases)}",
        "contradiction_recall": f"{matched_contradictions}/{total_contradictions}",
        "cases": results,
    }
    reports_dir = REPO_ROOT / "eval" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    out_file = reports_dir / f"bench_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    out_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nSummary: Verdicts {summary['verdict_unanimous_pass']} | Contradiction Recall {summary['contradiction_recall']}")
    print(f"Report written to: {out_file}")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Slop Gate 10-PDF calibration benchmark.")
    parser.add_argument("--cases", default=str(REPO_ROOT / "eval" / "expected_cases.json"))
    parser.add_argument("--model", default=None, help="Override reasoning model ID (e.g. gemini-2.5-pro)")
    parser.add_argument("--fast-model", default=None, help="Override fast Ghost-Deck model ID")
    parser.add_argument("--runs", type=int, default=1, help="Number of runs per PDF for variance check")
    args = parser.parse_args()
    asyncio.run(run_all(Path(args.cases), args.model, args.fast_model, args.runs))


if __name__ == "__main__":
    main()
