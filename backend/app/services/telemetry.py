"""Google Cloud Logging-compatible structured JSON logger, behavioral telemetry, rate limiting, and beta spend guardrails."""

from __future__ import annotations

import collections
import hashlib
import hmac
import json
import sys
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, Request

from app.config import settings
from app.services import session_store


class SlidingWindowRateLimiter:
    """Lightweight in-memory per-(bucket, user_hash) sliding window limiter."""

    def __init__(self) -> None:
        self._hits: dict[tuple[str, str], collections.deque[float]] = {}

    def check(self, *, bucket: str, user_hash: str, limit: int, window_seconds: float) -> bool:
        if limit <= 0:
            return True
        now = time.monotonic()
        cutoff = now - window_seconds
        key = (bucket, user_hash)
        dq = self._hits.get(key)
        if dq is None:
            dq = collections.deque()
            self._hits[key] = dq
        while dq and dq[0] < cutoff:
            dq.popleft()
        if len(dq) >= limit:
            return False
        dq.append(now)
        # Keep memory bounded under IP-spray attacks
        if len(self._hits) > 10_000:
            stale = [k for k, v in self._hits.items() if not v or v[-1] < cutoff]
            for k in stale[:2000]:
                self._hits.pop(k, None)
        return True

    def reset(self) -> None:
        self._hits.clear()


rate_limiter = SlidingWindowRateLimiter()


def extract_client_ip(request: Request | None) -> str:
    """Extract client IP respecting Cloud Run / load balancer X-Forwarded-For."""
    if request is None:
        return "local"
    xff = request.headers.get("x-forwarded-for", "").strip()
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def extract_user_hash(request: Request | None) -> str:
    """Privacy-safe 12-char salted SHA-256 hash of client IP (raw IPs are never logged or stored)."""
    ip = extract_client_ip(request)
    digest = hashlib.sha256(f"{settings.slop_log_salt}:{ip}".encode("utf-8")).hexdigest()
    return digest[:12]


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def estimate_cost_usd(
    *,
    prompt_tokens: int,
    output_tokens: int,
    thoughts_tokens: int,
    model: str | None = None,
) -> float:
    """Approximate Gemini API USD cost per call (<=200K context standard tier)."""
    m = (model or settings.llm_model_reasoning).lower()
    if "flash" in m:
        in_rate, out_rate = 0.50, 3.00
    else:
        in_rate, out_rate = 2.00, 12.00
    billable_out = max(0, int(output_tokens)) + max(0, int(thoughts_tokens))
    usd = (max(0, int(prompt_tokens)) / 1_000_000.0) * in_rate + (billable_out / 1_000_000.0) * out_rate
    return round(usd, 5)


def emit_cloud_json_log(
    *,
    severity: str,
    event: str,
    source: str,
    message: str,
    session_id: str | None = None,
    revision: int | None = None,
    stage: str | None = None,
    user_hash: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    """Emit a single-line Google Cloud Logging structured JSON entry to stdout.

    Cloud Run automatically indexes `severity`, `message`, and all top-level keys into
    `jsonPayload.*` in Logs Explorer (persists permanently even after scale-to-zero).
    """
    if not settings.slop_json_logs:
        return
    record: dict[str, Any] = {
        "severity": severity.upper(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "source": source,
        "message": message,
    }
    if session_id:
        record["session_id"] = session_id
    if revision is not None:
        record["revision"] = revision
    if stage:
        record["stage"] = stage
    if user_hash:
        record["user_hash"] = user_hash
    if payload:
        record["data"] = payload
    try:
        sys.stdout.write(json.dumps(record, default=str) + "\n")
        sys.stdout.flush()
    except Exception:
        pass


async def log_event(
    *,
    event: str,
    severity: str = "INFO",
    source: str = "backend",
    message: str | None = None,
    session_id: str | None = None,
    revision: int | None = None,
    stage: str | None = None,
    user_hash: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    """Emit structured Cloud Logging JSON AND persist to SQLite telemetry table (never raises)."""
    sev = severity.upper()
    msg = message or f"[{source}] {event}"
    emit_cloud_json_log(
        severity=sev,
        event=event,
        source=source,
        message=msg,
        session_id=session_id,
        revision=revision,
        stage=stage,
        user_hash=user_hash,
        payload=payload,
    )
    try:
        await session_store.store.record_telemetry_event(
            severity=sev,
            event=event,
            source=source,
            session_id=session_id,
            revision=revision,
            stage=stage,
            user_hash=user_hash,
            payload=payload,
        )
    except Exception:
        pass


def enforce_rate_limit(*, request: Request, bucket: str, limit: int, window_seconds: float, detail: str) -> str:
    user_hash = extract_user_hash(request)
    if not rate_limiter.check(bucket=bucket, user_hash=user_hash, limit=limit, window_seconds=window_seconds):
        raise HTTPException(status_code=429, detail=detail)
    return user_hash


async def enforce_sponsored_access(
    *,
    request: Request,
    x_gemini_api_key: str | None = None,
    x_beta_code: str | None = None,
    check_daily_quota: bool = False,
    check_gate2_answer_quota: bool = False,
) -> str:
    """Enforce optional SLOP_BETA_CODE, per-IP daily quota, and global daily run/USD caps.

    Users providing their own `X-Gemini-Api-Key` bypass sponsored quotas and beta codes.
    """
    user_hash = extract_user_hash(request)
    has_byok = bool((x_gemini_api_key or "").strip())
    if has_byok:
        return user_hash

    required_code = (settings.slop_beta_code or "").strip()
    if required_code:
        provided = (x_beta_code or request.headers.get("x-beta-code", "")).strip()
        if not provided or not constant_time_equals(provided, required_code):
            await log_event(
                event="beta_code_rejected",
                severity="WARNING",
                source="guardrail",
                user_hash=user_hash,
                payload={"path": str(request.url.path)},
            )
            raise HTTPException(
                status_code=401,
                detail="Beta access code required. Enter your invite code (or provide your own Gemini API key in Model & Key).",
            )

    if not settings.effective_gemini_key:
        return user_hash

    since_24h = time.time() - 86400.0

    # Global hard USD cap protects against distributed multi-IP traffic spikes
    if (check_daily_quota or check_gate2_answer_quota) and settings.slop_global_daily_usd_cap > 0:
        spent_24h = await session_store.store.sum_recent_sponsored_usd(since_ts=since_24h)
        if spent_24h >= settings.slop_global_daily_usd_cap:
            await log_event(
                event="global_daily_usd_cap_reached",
                severity="WARNING",
                source="guardrail",
                user_hash=user_hash,
                payload={"spent_24h_usd": spent_24h, "cap_usd": settings.slop_global_daily_usd_cap},
            )
            raise HTTPException(
                status_code=429,
                detail=(
                    "Today's shared sponsored beta budget has been reached. "
                    "You can continue immediately by pasting your own Gemini API key in Model & Key."
                ),
            )

    if check_daily_quota:
        if settings.slop_global_daily_run_limit > 0:
            global_used = await session_store.store.count_recent_events(
                event="gate1_started_sponsored",
                user_hash=None,
                since_ts=since_24h,
            )
            if global_used >= settings.slop_global_daily_run_limit:
                await log_event(
                    event="global_daily_run_cap_reached",
                    severity="WARNING",
                    source="guardrail",
                    user_hash=user_hash,
                    payload={"used_24h": global_used, "limit": settings.slop_global_daily_run_limit},
                )
                raise HTTPException(
                    status_code=429,
                    detail=(
                        "Today's shared sponsored beta capacity has been reached. "
                        "You can continue immediately by pasting your own Gemini API key in Model & Key."
                    ),
                )

        if settings.slop_daily_run_limit_per_ip > 0:
            used = await session_store.store.count_recent_events(
                event="gate1_started_sponsored",
                user_hash=user_hash,
                since_ts=since_24h,
            )
            if used >= settings.slop_daily_run_limit_per_ip:
                await log_event(
                    event="daily_quota_exceeded",
                    severity="WARNING",
                    source="guardrail",
                    user_hash=user_hash,
                    payload={"used_24h": used, "limit": settings.slop_daily_run_limit_per_ip},
                )
                raise HTTPException(
                    status_code=429,
                    detail=(
                        f"Daily sponsored beta limit reached ({settings.slop_daily_run_limit_per_ip} runs / 24h). "
                        "You can continue immediately by pasting your own Gemini API key in Model & Key."
                    ),
                )

    if check_gate2_answer_quota and settings.slop_daily_gate2_answer_limit_per_ip > 0:
        g2_used = await session_store.store.count_recent_events(
            event="gate2_answer_submitted",
            user_hash=user_hash,
            since_ts=since_24h,
        )
        if g2_used >= settings.slop_daily_gate2_answer_limit_per_ip:
            await log_event(
                event="gate2_daily_quota_exceeded",
                severity="WARNING",
                source="guardrail",
                user_hash=user_hash,
                payload={"used_24h": g2_used, "limit": settings.slop_daily_gate2_answer_limit_per_ip},
            )
            raise HTTPException(
                status_code=429,
                detail=(
                    f"Daily sponsored Q&A verification limit reached ({settings.slop_daily_gate2_answer_limit_per_ip} / 24h). "
                    "You can continue immediately by pasting your own Gemini API key in Model & Key."
                ),
            )

    return user_hash
