"""The only module that talks to the LLM provider (spec §8.7: swap in a local model here)."""

import logging
import time
from functools import lru_cache
from typing import TypeVar

import anthropic
from pydantic import BaseModel, ValidationError
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from rasid.config import get_settings
from rasid.schemas import Usage

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMError(RuntimeError):
    pass


@lru_cache
def get_client() -> anthropic.Anthropic:
    # Retries are owned by tenacity below, so the SDK's own retry loop is off.
    key = get_settings().anthropic_api_key.get_secret_value()
    return anthropic.Anthropic(api_key=key, max_retries=0)


def _is_transient(exc: BaseException) -> bool:
    """Retry rate limits, overload/5xx and network errors. A 400 is a bug in the request."""
    if isinstance(exc, anthropic.APIConnectionError):  # includes timeouts
        return True
    if isinstance(exc, anthropic.APIStatusError):
        return exc.status_code == 429 or exc.status_code >= 500
    return False


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(min=2, max=20),
    retry=retry_if_exception(_is_transient),
    reraise=True,
)
def _request(system_prompt: str, user_content: str, schema_model: type[T]):
    s = get_settings()
    kwargs = {
        "model": s.rasid_model,
        "max_tokens": s.rasid_max_tokens,
        # Long fixed prompt (rules + glossary + style notes) is cached across calls.
        "system": [
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "messages": [{"role": "user", "content": user_content}],
        "output_format": schema_model,  # structured output: response is guaranteed to match the schema
    }
    if s.rasid_fallbacks and "haiku" not in s.rasid_model:
        kwargs["extra_headers"] = {"anthropic-beta": FALLBACK_BETA}
        kwargs["extra_body"] = {"fallbacks": "default"}
    # Streaming avoids HTTP timeouts on long translations.
    with get_client().messages.stream(**kwargs) as stream:
        return stream.get_final_message()


def _usage(msg, seconds: float) -> Usage:
    u = msg.usage
    return Usage(
        model=msg.model,
        input_tokens=u.input_tokens,
        output_tokens=u.output_tokens,
        cache_read_tokens=u.cache_read_input_tokens or 0,
        cache_creation_tokens=u.cache_creation_input_tokens or 0,
        seconds=round(seconds, 2),
    )


def call_structured(
    system_prompt: str, user_content: str, schema_model: type[T]
) -> tuple[T, Usage]:
    """One LLM pass returning a validated `schema_model` instance and its token usage.

    On a validation failure, retries once with the error appended, then fails loudly.
    """
    content = user_content
    for attempt in (1, 2):
        t0 = time.perf_counter()
        try:
            msg = _request(system_prompt, content, schema_model)
        except ValidationError as e:
            if attempt == 2:
                raise LLMError(f"Output failed schema validation twice: {e}") from e
            log.warning("Schema validation failed; retrying once")
            content = f"{user_content}\n\n<previous_error>\n{e}\n</previous_error>"
            continue
        except anthropic.APIStatusError as e:
            raise LLMError(
                f"API error {e.status_code}: {e.message} (request_id={e.request_id})"
            ) from e
        except anthropic.APIConnectionError as e:
            raise LLMError(f"Could not reach the API after retries: {e}") from e
        usage = _usage(msg, time.perf_counter() - t0)
        log.info("LLM usage: %s", usage.model_dump())

        if msg.stop_reason == "refusal":
            details = getattr(msg, "stop_details", None)
            raise LLMError(
                f"Model declined the request (category: {getattr(details, 'category', None)})"
            )
        if msg.stop_reason == "max_tokens":
            raise LLMError(
                f"Output hit max_tokens ({get_settings().rasid_max_tokens}); "
                "raise RASID_MAX_TOKENS or shorten the article"
            )
        if msg.parsed_output is None:
            raise LLMError(
                f"No structured output returned (stop_reason={msg.stop_reason})"
            )
        return msg.parsed_output, usage
    raise AssertionError("unreachable")
