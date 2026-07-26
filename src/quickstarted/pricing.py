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
            return cls()
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
