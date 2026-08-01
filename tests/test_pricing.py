"""Prices: the explicit book, the optional live one, and the token gotcha."""

import sys
import types

import pytest

from quickstarted.agents.base import AgentOutcome
from quickstarted.pricing import LivePriceBook, ModelPrice, PriceBook

OUTCOME = AgentOutcome(
    "completed", 6,
    input_tokens=12, output_tokens=1150,
    cache_write_tokens=11204, cache_read_tokens=33181,
)


def test_an_explicit_price_book_prices_all_four_counters():
    book = PriceBook({"claude-opus-5": ModelPrice(5.0, 25.0, 6.25, 0.5)})
    expected = (12 * 5.0 + 1150 * 25.0 + 11204 * 6.25 + 33181 * 0.5) / 1_000_000
    assert book.estimate("claude:claude-opus-5", OUTCOME) == pytest.approx(expected)


def test_no_source_of_rates_means_no_dollars(monkeypatch):
    """On 3.9, or without the extra, tokens are still reported and cost is not."""
    monkeypatch.setattr(LivePriceBook, "available", staticmethod(lambda: False))
    book = PriceBook.load(None)
    assert not book
    assert book.estimate("claude:claude-opus-5", OUTCOME) is None


def test_live_prices_are_used_when_the_extra_is_installed(monkeypatch):
    monkeypatch.setattr(LivePriceBook, "available", staticmethod(lambda: True))
    assert isinstance(PriceBook.load(None), LivePriceBook)


def test_live_pricing_sends_the_whole_prompt_not_the_uncached_remainder(monkeypatch):
    """genai-prices subtracts the cache buckets from `input_tokens` itself.

    quickstarted stores the three counters exclusively, so the total is their
    sum. Passing the uncached figure alone would underreport every cached run,
    which is most of them.
    """
    seen = {}

    class FakeUsage:
        def __init__(self, **kwargs):
            seen.update(kwargs)

    class FakePrice:
        total_price = 1.25

    module = types.ModuleType("genai_prices")
    module.Usage = FakeUsage
    module.calc_price = lambda usage, model_ref, provider_id: FakePrice()
    monkeypatch.setitem(sys.modules, "genai_prices", module)

    assert LivePriceBook().estimate("claude:claude-opus-5", OUTCOME) == 1.25
    assert seen["input_tokens"] == 12 + 11204 + 33181
    assert seen["cache_write_tokens"] == 11204
    assert seen["cache_read_tokens"] == 33181
    assert seen["output_tokens"] == 1150


def test_an_unknown_model_is_a_missing_number_not_a_crash(monkeypatch):
    def explode(*args, **kwargs):
        raise RuntimeError("no such model")

    module = types.ModuleType("genai_prices")
    module.Usage = lambda **kwargs: None
    module.calc_price = explode
    monkeypatch.setitem(sys.modules, "genai_prices", module)

    assert LivePriceBook().estimate("claude:nonesuch", OUTCOME) is None


def test_an_agent_with_no_known_provider_is_not_priced():
    assert LivePriceBook().estimate("replay", OUTCOME) is None
