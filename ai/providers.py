"""LLM provider interface.

The rest of the app talks to a `GuideProvider`, so switching models means adding one class
(e.g. a Claude provider using the anthropic SDK) and selecting it in `get_provider()`,
not editing the guide pipeline, the prompts or the API.
"""
import logging
import os
import time
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from google import genai
from google.genai import errors, types

logger = logging.getLogger(__name__)

DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"  # latest stable Flash (Gemini models page, 2026-10-01)
# Used when the main model is rate-limited or overloaded: the latest stable Flash-Lite. Quotas
# are per model, so it has its own allowance. GEMINI_FALLBACK_MODEL="" switches it off.
DEFAULT_GEMINI_FALLBACK_MODEL = "gemini-3.5-flash-lite"
# After the main model fails on quota/overload, requests go straight to the fallback for this
# long. Per process, keyed by model.
MAIN_MODEL_COOLDOWN_S = 300
_cooldown_until = {}

# Paid-tier list prices, USD per 1M tokens, from https://ai.google.dev/gemini-api/docs/pricing
# (last updated 2026-10-01; Flash-Lite prices from the same page). Thinking tokens are billed as output. Each model has a schedule of
# (effective_from, input, output) so announced price changes apply on the right date.
GEMINI_PRICES = {
    "gemini-3.8-flash": [("2000-01-01", 0.75, 3.75), ("2027-01-01", 1.50, 7.50)],
    "gemini-3.5-flash": [("2000-01-01", 1.50, 9.00)],
    "gemini-3.5-flash-lite": [("2000-01-01", 0.30, 2.50)],
    "gemini-2.5-flash": [("2000-01-01", 0.30, 2.50)],
}


def price_per_million(model, on=None):
    """(input, output) USD per 1M tokens for `model` on date `on` (default today), or None."""
    on = (on or date.today()).isoformat()
    applicable = [(start, inp, out) for start, inp, out in GEMINI_PRICES.get(model, []) if start <= on]
    return applicable[-1][1:] if applicable else None


# Bound how long one request can wait on the LLM. The SDK retries 408/429/5xx with
# exponential backoff; 2 attempts keeps the worst case near 2 x timeout.
LLM_TIMEOUT_MS = int(os.getenv("LLM_TIMEOUT_MS", "15000"))
LLM_MAX_ATTEMPTS = 2


class AIUnavailableError(RuntimeError):
    """The AI provider can't be used (no API key, network failure, server error...)."""


class AINotConfiguredError(AIUnavailableError):
    """No API key: AI features are off by configuration (a supported setup, not an outage)."""


class AIRateLimitedError(AIUnavailableError):
    """The provider rejected the request for quota/rate reasons (after the SDK's retries)."""


class AIOverloadedError(AIUnavailableError):
    """The provider answered with a server error such as 503 "high demand" (after retries)."""


@dataclass
class LLMResponse:
    text: str
    model: str
    input_tokens: int
    output_tokens: int   # includes thinking tokens, which providers bill as output
    latency_ms: int
    cost_usd: float


class GuideProvider(Protocol):
    model: str

    def generate(self, prompt: str, json_schema: dict | None = None) -> LLMResponse:
        """Returns the model's text. With `json_schema`, the model is asked for JSON matching it
        (the caller still validates: providers can return malformed or off-schema output)."""
        ...


# ── Gemini ──────────────────────────────────────────────────────────────────

# Created on first use, not at import: a missing key must only disable AI features,
# not stop the whole API from starting.
_client = None


def get_client():
    global _client
    if _client is None:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise AINotConfiguredError("GEMINI_API_KEY is not set")
        _client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=LLM_TIMEOUT_MS,
                retry_options=types.HttpRetryOptions(attempts=LLM_MAX_ATTEMPTS, initial_delay=1.0, max_delay=5.0),
            ),
        )
    return _client


class GeminiProvider:
    def __init__(self, model=DEFAULT_GEMINI_MODEL, fallback_model=None):
        self.model = model
        self.fallback_model = fallback_model if fallback_model != model else None

    def generate(self, prompt, json_schema=None):
        """Asks the main model; if it is rate-limited or overloaded, asks the fallback model once.
        The response names the model that actually answered (for cost and storage); its latency is
        what the caller waited, including a failed attempt on the main model."""
        start = time.perf_counter()
        if self.fallback_model and time.monotonic() < _cooldown_until.get(self.model, 0):
            response = self._generate(self.fallback_model, prompt, json_schema)  # main model still cooling down
        else:
            try:
                response = self._generate(self.model, prompt, json_schema)
            except (AIRateLimitedError, AIOverloadedError) as e:
                if not self.fallback_model:
                    raise
                # A used-up quota doesn't come back in seconds: skip the main model for a while
                # instead of paying its timeout and retries on every request.
                _cooldown_until[self.model] = time.monotonic() + MAIN_MODEL_COOLDOWN_S
                logger.warning("%s unavailable (%s); using %s for the next %d s", self.model,
                               type(e).__name__, self.fallback_model, MAIN_MODEL_COOLDOWN_S)
                response = self._generate(self.fallback_model, prompt, json_schema)
        response.latency_ms = int((time.perf_counter() - start) * 1000)
        return response

    def _generate(self, model, prompt, json_schema):
        config = None
        if json_schema is not None:
            config = types.GenerateContentConfig(response_mime_type="application/json",
                                                 response_json_schema=json_schema)
        try:
            response = get_client().models.generate_content(model=model, contents=prompt, config=config)
        except errors.APIError as e:
            if e.code == 429:
                raise AIRateLimitedError(str(e)) from e
            if isinstance(e.code, int) and e.code >= 500:
                raise AIOverloadedError(f"{type(e).__name__}: {e}") from e
            raise AIUnavailableError(f"{type(e).__name__}: {e}") from e
        except AIUnavailableError:
            raise
        except Exception as e:  # network errors, timeouts
            raise AIUnavailableError(f"{type(e).__name__}: {e}") from e

        usage = getattr(response, "usage_metadata", None)
        input_tokens = _as_int(getattr(usage, "prompt_token_count", 0))
        output_tokens = (_as_int(getattr(usage, "candidates_token_count", 0))
                         + _as_int(getattr(usage, "thoughts_token_count", 0)))
        prices = price_per_million(model)
        if prices is None:
            logger.warning("No price known for model %s; recording cost as 0", model)
            prices = (0.0, 0.0)
        cost = (input_tokens * prices[0] + output_tokens * prices[1]) / 1_000_000
        return LLMResponse(text=response.text or "", model=model, input_tokens=input_tokens,
                           output_tokens=output_tokens, latency_ms=0, cost_usd=round(cost, 6))  # set by generate()


def _as_int(value):
    return value if isinstance(value, int) else 0


def get_provider() -> GuideProvider:
    """The configured provider. Gemini today; a new provider is one class plus one line here."""
    return GeminiProvider(os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL),
                          fallback_model=os.getenv("GEMINI_FALLBACK_MODEL", DEFAULT_GEMINI_FALLBACK_MODEL) or None)
