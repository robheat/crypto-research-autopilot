"""ChainTVL scraper — https://www.chaintvl.com has no public API, so this
parses its server-rendered HTML directly. Fine as long as the site's markup
stays stable; every selector here was checked against the live page.
"""
from __future__ import annotations

import re
from typing import Any

import httpx
from bs4 import BeautifulSoup

CHAINTVL_URL = "https://www.chaintvl.com"
_HEADERS = {"user-agent": "Mozilla/5.0 (compatible; CryptoResearchAutopilot/1.0)"}

_TOTAL_OUTFLOW_RE = re.compile(r"^Total outflow")
_TOTAL_INFLOW_RE = re.compile(r"^Total inflow")


def _parse_summary_cards(soup: BeautifulSoup) -> dict[str, dict[str, str | None]]:
    """The three top-of-page stat cards: Total DeFi TVL, 7-day change, stablecoin supply."""
    summary: dict[str, dict[str, str | None]] = {}
    for card in soup.select(".viz-card"):
        label_el = card.select_one("span.text-sm")
        value_el = card.select_one("span.text-3xl, span.text-2xl")
        if not label_el or not value_el:
            continue
        delta_el = card.select_one("span.text-sm.font-medium")
        summary[label_el.get_text(strip=True)] = {
            "value": value_el.get_text(strip=True),
            "delta": delta_el.get_text(" ", strip=True) if delta_el else None,
        }
    return summary


def _parse_chains_table(soup: BeautifulSoup) -> list[dict[str, str]]:
    """Per-chain TVL row, in the page's default sort (TVL descending)."""
    table = soup.select_one("table")
    if not table:
        return []
    rows: list[dict[str, str]] = []
    for tr in table.select("tbody tr"):
        cells = tr.find_all("td")
        if len(cells) < 6:
            continue
        name_el = cells[0].select_one("span")
        name = name_el.get_text(strip=True) if name_el else cells[0].get_text(strip=True)
        if not name:
            continue
        rows.append({
            "chain": name,
            "tvl": cells[1].get_text(strip=True),
            "change_24h": cells[2].get_text(strip=True),
            "change_7d": cells[3].get_text(strip=True),
            "change_30d": cells[4].get_text(strip=True),
            "stablecoin_supply": cells[5].get_text(strip=True),
        })
    return rows


def _parse_flow_totals(soup: BeautifulSoup) -> dict[str, str]:
    """Aggregate inflow/outflow totals from the /flows page's summary cards."""
    totals: dict[str, str] = {}
    for label_div in soup.find_all("div"):
        text = label_div.get_text(strip=True)
        if not text or label_div.find("div"):
            continue  # only leaf divs carry the label text, not their ancestors
        is_outflow = bool(_TOTAL_OUTFLOW_RE.match(text))
        is_inflow = bool(_TOTAL_INFLOW_RE.match(text))
        if not (is_outflow or is_inflow):
            continue
        value_div = label_div.find_next_sibling("div")
        if value_div:
            totals[text] = value_div.get_text(strip=True)
    return totals


async def get_tvl_snapshot() -> dict[str, Any]:
    """Fetch + parse the ChainTVL home page (TVL summary, per-chain table) and
    the /flows page (24h capital rotation totals).
    """
    async with httpx.AsyncClient(timeout=20, headers=_HEADERS) as client:
        home_resp = await client.get(f"{CHAINTVL_URL}/")
        home_resp.raise_for_status()
        flows_resp = await client.get(f"{CHAINTVL_URL}/flows")
        flows_resp.raise_for_status()

    home_soup = BeautifulSoup(home_resp.text, "html.parser")
    flows_soup = BeautifulSoup(flows_resp.text, "html.parser")

    return {
        "summary": _parse_summary_cards(home_soup),
        "chains": _parse_chains_table(home_soup),
        "flows": _parse_flow_totals(flows_soup),
    }
