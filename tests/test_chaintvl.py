"""Parser tests for the ChainTVL scraper, against saved HTML snapshots.

ChainTVL has no public API — these fixtures are real server-rendered HTML
pulled from chaintvl.com, so a parser break here means the site's markup
changed and _parse_* needs updating.
"""
from __future__ import annotations

from pathlib import Path

from bs4 import BeautifulSoup

from app.services.chaintvl import _parse_chains_table, _parse_flow_totals, _parse_summary_cards

FIXTURES = Path(__file__).parent / "fixtures" / "chaintvl"
HOME_SOUP = BeautifulSoup((FIXTURES / "home.html").read_text(encoding="utf-8"), "html.parser")
FLOWS_SOUP = BeautifulSoup((FIXTURES / "flows.html").read_text(encoding="utf-8"), "html.parser")


def test_summary_cards_parse_value_and_delta():
    summary = _parse_summary_cards(HOME_SOUP)
    assert summary["Total DeFi TVL"]["value"].startswith("$")
    assert "24h" in summary["Total DeFi TVL"]["delta"]
    assert "Tracked stablecoin supply (top chains)" in summary


def test_chains_table_parses_every_row_with_all_fields():
    chains = _parse_chains_table(HOME_SOUP)
    assert len(chains) > 10
    top = chains[0]
    assert top["chain"] == "Ethereum"
    for field in ("tvl", "change_24h", "change_7d", "change_30d", "stablecoin_supply"):
        assert top[field]


def test_flow_totals_parses_inflow_and_outflow():
    totals = _parse_flow_totals(FLOWS_SOUP)
    assert totals["Total outflow (losing chains)"].startswith("$")
    assert totals["Total inflow (gaining chains)"].startswith("$")
