"""Pluggable multimodal LLM provider abstraction + Google Gemini implementation."""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import random
import tempfile
from pathlib import Path
from typing import Protocol, TypeVar

from pydantic import BaseModel

from app.config import settings
from app.schemas.gate1 import TokenUsage

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


@dataclasses.dataclass(slots=True)
class TextPart:
    text: str


@dataclasses.dataclass(slots=True)
class ImagePart:
    data: bytes
    mime_type: str = "image/jpeg"


@dataclasses.dataclass(slots=True)
class LLMResult:
    parsed: BaseModel
    model: str
    usage: TokenUsage
    latency_ms: int


class LLMProviderError(RuntimeError):
    """Raised when an LLM call fails after retries or due to invalid config."""


class LLMProvider(Protocol):
    async def generate_structured(
        self,
        *,
        model: str,
        system_prompt: str,
        parts: list[TextPart | ImagePart],
        response_schema: type[T],
        temperature: float = 0.1,
        max_output_tokens: int = 8192,
        timeout_seconds: int = 120,
    ) -> tuple[T, TokenUsage]: ...


def _is_transient_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    transient_markers = ("429", "503", "504", "500", "resource_exhausted", "unavailable", "deadline", "timeout", "temporarily")
    non_retry_markers = ("400", "401", "403", "invalid_argument", "api_key", "safety", "blocked")
    if any(m in msg for m in non_retry_markers):
        return False
    return any(m in msg for m in transient_markers)


class GeminiProvider:
    """Google Gemini multimodal provider using the official `google-genai` SDK."""

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = (api_key or settings.effective_gemini_key).strip()
        if not self.api_key:
            raise LLMProviderError("GEMINI_API_KEY is not configured.")

    async def generate_structured(
        self,
        *,
        model: str,
        system_prompt: str,
        parts: list[TextPart | ImagePart],
        response_schema: type[T],
        temperature: float = 0.1,
        max_output_tokens: int = 8192,
        timeout_seconds: int = 120,
    ) -> tuple[T, TokenUsage]:
        from google import genai
        from google.genai import types

        # Preview models (e.g. gemini-3.1-pro-preview, gemini-3-flash-preview) require v1beta
        client = genai.Client(
            api_key=self.api_key,
            http_options=types.HttpOptions(api_version="v1beta"),
        )

        total_img_bytes = sum(len(p.data) for p in parts if isinstance(p, ImagePart))
        use_files_api = total_img_bytes > settings.llm_inline_max_bytes
        uploaded_files: list[object] = []

        try:
            content_parts: list[object] = []
            for part in parts:
                if isinstance(part, TextPart):
                    content_parts.append(types.Part.from_text(text=part.text))
                elif isinstance(part, ImagePart):
                    if use_files_api:
                        suffix = ".jpg" if "jpeg" in part.mime_type else ".png"
                        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tf:
                            tf.write(part.data)
                            tmp_path = Path(tf.name)
                        try:
                            fobj = await client.aio.files.upload(file=str(tmp_path), config={"mime_type": part.mime_type})
                            uploaded_files.append(fobj)
                            content_parts.append(fobj)
                        finally:
                            tmp_path.unlink(missing_ok=True)
                    else:
                        content_parts.append(types.Part.from_bytes(data=part.data, mime_type=part.mime_type))

            config = types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                response_mime_type="application/json",
                response_schema=response_schema,
            )

            delays = [1.0, 3.0, 7.0]
            last_exc: Exception | None = None
            for attempt in range(len(delays) + 1):
                try:
                    response = await asyncio.wait_for(
                        client.aio.models.generate_content(
                            model=model,
                            contents=content_parts,
                            config=config,
                        ),
                        timeout=timeout_seconds,
                    )
                    # Check finish reason for truncation
                    candidates = getattr(response, "candidates", None) or []
                    if candidates:
                        fr = str(getattr(candidates[0], "finish_reason", "") or "")
                        if "MAX_TOKENS" in fr.upper():
                            raise LLMProviderError(f"Model output truncated (finish_reason={fr}).")

                    raw_text = (getattr(response, "text", None) or "").strip()
                    if not raw_text:
                        raise LLMProviderError("Empty response returned by Gemini API.")

                    parsed = response_schema.model_validate_json(raw_text)

                    um = getattr(response, "usage_metadata", None)
                    usage = TokenUsage(
                        prompt_tokens=int(getattr(um, "prompt_token_count", 0) or 0),
                        output_tokens=int(getattr(um, "candidates_token_count", 0) or 0),
                        thoughts_tokens=int(getattr(um, "thoughts_token_count", 0) or 0),
                    )
                    return parsed, usage
                except Exception as exc:
                    last_exc = exc
                    if attempt < len(delays) and _is_transient_error(exc):
                        jitter = random.uniform(0.0, 0.5)
                        logger.warning("Transient Gemini error on attempt %d (%s); retrying...", attempt + 1, exc)
                        await asyncio.sleep(delays[attempt] + jitter)
                        continue
                    raise LLMProviderError(f"Gemini call failed ({model}): {exc}") from exc

            raise LLMProviderError(f"Gemini call failed after retries: {last_exc}")
        finally:
            for fobj in uploaded_files:
                fname = getattr(fobj, "name", None)
                if fname:
                    try:
                        await client.aio.files.delete(name=fname)
                    except Exception:
                        pass
