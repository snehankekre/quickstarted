"""Optional cost estimation.

There are deliberately no built-in prices. Vendor rates change, a stale table
baked into a benchmarking tool would quietly misreport what a run costs, and a
wrong number here is worse than no number. Supply rates yourself:

    QUICKSTARTED_PRICES=/path/to/prices.json

    {
      "claude-opus-5": {
        "input": 5.0, "output": 25.0, "cache_write": 6.25, "cache_read": 0.5
      }
    }

Units are US dollars per million tokens, matching how vendors publish them.
Token counts are always reported; dollars appear only when you provide rates.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

PRICES_ENV = "QUICKSTARTED_PRICES"
_PER_MILLION = 1_000_000.0


@dataclass(frozen=True)
class ModelPrice:
    input: float = 0.0
    output: float = 0.0
    cache_write: float = 0.0
    cache_read: float = 0.0

    def cost(
        self,
        input_tokens: int,
        output_tokens: int,
        cache_write_tokens: int = 0,
        cache_read_tokens: int = 0,
    ) -> float:
        return (
            input_tokens * self.input
            + output_tokens * self.output
            + cache_write_tokens * self.cache_write
            + cache_read_tokens * self.cache_read
        ) / _PER_MILLION


class PriceBook:
    def __init__(self, prices: dict[str, ModelPrice] | None = None):
        self.prices = prices or {}

    def __bool__(self) -> bool:
        return bool(self.prices)

    def for_model(self, model: str) -> ModelPrice | None:
        if model in self.prices:
            return self.prices[model]
        # Adapters report names like "claude:claude-opus-5"; match the tail.
        tail = model.rsplit(":", 1)[-1]
        return self.prices.get(tail)

    def estimate(self, model: str, outcome) -> float | None:
        price = self.for_model(model)
        if price is None:
            return None
        return price.cost(
            outcome.input_tokens,
            outcome.output_tokens,
            outcome.cache_write_tokens,
            outcome.cache_read_tokens,
        )

    @classmethod
    def load(cls, path: str | None = None) -> PriceBook:
        path = path or os.environ.get(PRICES_ENV)
        if not path:
            # Nothing was supplied, so fall back to a maintained price source if
            # one is installed. The rule that keeps this honest is unchanged: no
            # table of rates lives in this repository, where it would rot.
            return LivePriceBook() if LivePriceBook.available() else cls()
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        prices = {}
        for model, fields in data.items():
            if not isinstance(fields, dict):
                raise ValueError(f"price entry for {model!r} must be a mapping")
            prices[model] = ModelPrice(
                input=float(fields.get("input", 0.0)),
                output=float(fields.get("output", 0.0)),
                cache_write=float(fields.get("cache_write", 0.0)),
                cache_read=float(fields.get("cache_read", 0.0)),
            )
        return cls(prices)


#: The agent prefix each vendor's prices are published under.
_PROVIDERS = {"claude": "anthropic", "openai": "openai", "gemini": "google"}


class LivePriceBook(PriceBook):
    """Rates from `genai-prices`, when `pip install quickstarted[prices]` put it there.

    A first run otherwise reports tokens and no dollars until somebody writes a
    JSON file by hand, which almost nobody does, so the cost of a sweep stays
    abstract right up until the invoice.

    This does not reintroduce the thing the explicit path exists to avoid. The
    rates come from a package that is updated when vendors change them, not from
    a table checked into this repository that would quietly go stale.
    """

    @staticmethod
    def available() -> bool:
        import importlib.util

        return importlib.util.find_spec("genai_prices") is not None

    def __bool__(self) -> bool:
        return True

    def estimate(self, model: str, outcome) -> float | None:
        try:
            from genai_prices import Usage, calc_price
        except ImportError:
            return None
        prefix, _, tail = model.partition(":")
        provider = _PROVIDERS.get(prefix)
        name = tail or prefix
        if provider is None or not name:
            return None
        # genai-prices treats `input_tokens` as the whole prompt and subtracts
        # the cache buckets to find what was billed at the uncached rate. The
        # three counters here are exclusive, so the total is their sum. Passing
        # the uncached figure alone would underreport every cached run.
        try:
            price = calc_price(
                Usage(
                    input_tokens=(
                        outcome.input_tokens
                        + outcome.cache_write_tokens
                        + outcome.cache_read_tokens
                    ),
                    cache_write_tokens=outcome.cache_write_tokens,
                    cache_read_tokens=outcome.cache_read_tokens,
                    output_tokens=outcome.output_tokens,
                ),
                model_ref=name,
                provider_id=provider,
            )
        except Exception:
            # An unknown model is a missing number, never a crashed sweep.
            return None
        return float(price.total_price)


def refresh_live_prices(timeout: float = 10.0) -> bool:
    """Fetch current rates before pricing a sweep. True when the fetch ran.

    The snapshot bundled with `genai-prices` lags new models, and the models
    worth benchmarking are the new ones. This asks for the current data, which
    helps when upstream has caught up and does nothing when it has not: at the
    time of writing neither the snapshot nor the live data prices
    `claude-opus-5`, so a Claude sweep still needs an explicit price book.
    Whatever is missing is named in the summary rather than dropped.

    Opt-in, because a benchmarking run should not make a surprise network call
    to price itself.
    """
    try:
        from genai_prices import UpdatePrices
    except ImportError:
        return False
    import time

    try:
        with UpdatePrices():
            # The fetch runs in a background thread. Give it a bounded moment
            # rather than blocking a paid sweep on somebody else's CDN.
            time.sleep(min(timeout, 2.0))
        return True
    except Exception:
        return False
