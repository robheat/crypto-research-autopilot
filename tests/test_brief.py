"""Regression tests for the brief -> article pipeline.

Every test here corresponds to a bug that shipped to production at least once.
"""
from __future__ import annotations

import pytest

from app.services.brief import (
    _as_number,
    _brief_to_article,
    _detect_assets,
    _extract_lead_signal,
    _extract_tags,
    _first_prose_paragraph,
    _format_global_market,
    _format_prices,
    _md_to_plaintext,
    _pick_category,
    _prepare_article_body,
    _truncate_at_boundary,
)

SAMPLE_BRIEF = """## Morning Brief — Monday, June 01, 2026

### 1. OVERNIGHT MOVES

Watchlist prices closed lower across the board — BTC at $72,791 (-1.3%), ETH at
$1,985 (-1.7%). The weekend torpor has given way to a modest selloff.

### 2. NARRATIVE PULSE

- **The L2 narrative signal has been nullified.** OP's disappearance confirms it.

### 4. SIGNAL NOT TO MISS

**OP's disappearance from the trending board confirms the rotation was noise.**
The most durable speculative signal is LAB.

### 5. OPEN QUESTION

What has enough structural bid to break the market out of this slide?
"""


# ---------------------------------------------------------------------------
# Summary extraction — every article shipped with summary "1. OVERNIGHT MOVES"
# ---------------------------------------------------------------------------

def test_summary_is_prose_not_a_section_heading():
    plain = _md_to_plaintext(SAMPLE_BRIEF)
    summary = _first_prose_paragraph(plain)
    assert "OVERNIGHT MOVES" not in summary
    assert summary.startswith("Watchlist prices closed lower")


def test_summary_skips_the_duplicate_title_line():
    plain = _md_to_plaintext(SAMPLE_BRIEF)
    assert not _first_prose_paragraph(plain).lower().startswith("morning brief")


def test_article_summary_fits_meta_description_budget():
    _, article = _brief_to_article(SAMPLE_BRIEF, "2026-06-01")
    assert 0 < len(article["summary"]) <= 160
    assert article["summary"] != "1. OVERNIGHT MOVES"


@pytest.mark.parametrize(
    "text,limit",
    [("word " * 100, 160), ("Short enough.", 160), ("nospaceatallhere" * 40, 60)],
)
def test_truncate_never_exceeds_limit(text, limit):
    # The ellipsis is appended after trimming, so allow one extra character.
    assert len(_truncate_at_boundary(text, limit)) <= limit + 1


def test_truncate_does_not_cut_mid_word():
    out = _truncate_at_boundary("alpha bravo charlie delta echo foxtrot", 20)
    assert "…" in out
    assert not out.rstrip("…").endswith(("cha", "delt"))


# ---------------------------------------------------------------------------
# Body structure — the published body used to be flattened to plaintext
# ---------------------------------------------------------------------------

def test_body_keeps_heading_structure():
    body = _prepare_article_body(SAMPLE_BRIEF)
    assert "## Overnight Moves" in body
    assert "## Signal Not To Miss" in body


def test_body_drops_the_duplicate_title_heading():
    body = _prepare_article_body(SAMPLE_BRIEF)
    assert "Morning Brief —" not in body


def test_body_preserves_lists_and_emphasis():
    body = _prepare_article_body(SAMPLE_BRIEF)
    assert "- **The L2 narrative signal" in body


def test_article_exposes_markdown_html_and_text_bodies():
    _, article = _brief_to_article(SAMPLE_BRIEF, "2026-06-01")
    assert article["bodyFormat"] == "markdown"
    assert article["body"].startswith("## ")
    assert "<h2" in article["bodyHtml"]
    assert "##" not in article["bodyText"]


# ---------------------------------------------------------------------------
# Tag / category matching — substring matching tagged "whether" as ethereum
# ---------------------------------------------------------------------------

def test_tags_use_word_boundaries():
    tags = _extract_tags("whether the console solution matters is unclear")
    assert "ethereum" not in tags
    assert "solana" not in tags


def test_tags_still_match_real_mentions():
    assert "ethereum" in _extract_tags("eth broke $2k overnight")
    assert "bitcoin" in _extract_tags("bitcoin dominance eased")


def test_tag_list_is_capped_and_sorted():
    tags = _extract_tags(
        "bitcoin ethereum solana defi stablecoin nft regulation policy "
        "on-chain narrative sentiment institutional"
    )
    assert tags == sorted(tags)
    assert len(tags) <= 8


def test_category_ignores_substring_noise():
    assert _pick_category("whether whether whether bitcoin bitcoin bitcoin") == "bitcoin"


def test_detect_assets_ignores_substrings():
    assert _detect_assets("whether the console works") == []
    assert _detect_assets("BTC and ETH both fell") == ["Bitcoin", "Ethereum"]


# ---------------------------------------------------------------------------
# Numeric guards — these raised ValueError/TypeError and killed scheduled runs
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value", [None, "N/A", "", {}, [], True])
def test_as_number_rejects_non_numerics(value):
    assert _as_number(value) is None


@pytest.mark.parametrize("value,expected", [(1, 1.0), ("2.5", 2.5), (0, 0.0)])
def test_as_number_accepts_numerics(value, expected):
    assert _as_number(value) == expected


def test_prices_survive_a_missing_usd_quote():
    out = _format_prices(
        {"bitcoin": {"usd_24h_change": -1.3}},
        [{"symbol": "BTC", "coingecko_id": "bitcoin"}],
    )
    assert "price unavailable" in out
    assert "-1.3%" in out


def test_prices_format_normally_when_complete():
    out = _format_prices(
        {"bitcoin": {"usd": 72791.5, "usd_24h_change": -1.34}},
        [{"symbol": "BTC", "coingecko_id": "bitcoin"}],
    )
    assert "$72,791.5000" in out
    assert "(-1.3%)" in out


def test_prices_tolerate_null_change():
    out = _format_prices(
        {"bitcoin": {"usd": 100, "usd_24h_change": None}},
        [{"symbol": "BTC", "coingecko_id": "bitcoin"}],
    )
    assert "$100.0000" in out


# ---------------------------------------------------------------------------
# CoinGecko global — cap and volume were read with CoinMarketCap's key layout
# ---------------------------------------------------------------------------

def test_global_market_reads_coingecko_layout():
    out = _format_global_market(
        {
            "total_market_cap": {"usd": 2.4e12},
            "total_volume": {"usd": 8.9e10},
            "market_cap_percentage": {"btc": 57.2, "eth": 11.1},
            "market_cap_change_percentage_24h_usd": -1.42,
        }
    )
    assert "Total market cap: $2,400,000,000,000" in out
    assert "24h volume: $89,000,000,000" in out
    assert "BTC dominance: 57.2%" in out
    assert "ETH dominance: 11.1%" in out
    assert "-1.42%" in out


def test_global_market_handles_empty_and_partial_payloads():
    assert _format_global_market({}) == "No global market data available."
    assert "BTC dominance: 57.2%" in _format_global_market(
        {"market_cap_percentage": {"btc": 57.2}}
    )


# ---------------------------------------------------------------------------
# SEO fields and schema.org
# ---------------------------------------------------------------------------

def test_canonical_url_points_at_the_article_not_the_site_root():
    slug, article = _brief_to_article(SAMPLE_BRIEF, "2026-06-01")
    expected = f"https://cryptocatalyst.news/articles/{slug}"
    assert article["canonicalUrl"] == expected
    assert article["sourceUrl"] == expected


def test_image_alt_is_present_and_descriptive():
    _, article = _brief_to_article(SAMPLE_BRIEF, "2026-06-01")
    assert "Bitcoin" in article["imageAlt"]
    assert article["imageAlt"].endswith(".")


def test_schema_is_a_valid_newsarticle_shape():
    _, article = _brief_to_article(SAMPLE_BRIEF, "2026-06-01")
    schema = article["schema"]
    assert schema["@context"] == "https://schema.org"
    assert schema["@type"] == "AnalysisNewsArticle"
    assert len(schema["headline"]) <= 110  # Google News hard limit
    assert schema["mainEntityOfPage"]["@id"] == article["canonicalUrl"]
    assert schema["publisher"]["logo"]["@type"] == "ImageObject"
    assert schema["inLanguage"] == "en"
    assert schema["wordCount"] > 0


def test_schema_entity_links_the_assets_discussed():
    _, article = _brief_to_article(SAMPLE_BRIEF, "2026-06-01")
    names = {entity["name"] for entity in article["schema"]["about"]}
    assert {"Bitcoin", "Ethereum"} <= names
    for entity in article["schema"]["about"]:
        assert any("wikipedia.org" in url for url in entity["sameAs"])


def test_image_attachment_absolutises_the_url():
    from app.services.brief import _attach_image

    _, article = _brief_to_article(SAMPLE_BRIEF, "2026-06-01")
    _attach_image(article, "/images/articles/x.png")
    assert article["imageUrl"] == "https://cryptocatalyst.news/images/articles/x.png"
    assert article["schema"]["image"]["url"] == article["imageUrl"]
    assert article["schema"]["image"]["caption"] == article["imageAlt"]


def test_tweet_stays_within_budget_and_carries_real_prose():
    _, article = _brief_to_article(SAMPLE_BRIEF, "2026-06-01")
    assert len(article["standaloneTweet"]) <= 201
    assert "OVERNIGHT MOVES" not in article["standaloneTweet"]


def test_reading_time_is_at_least_one_minute():
    _, article = _brief_to_article(SAMPLE_BRIEF, "2026-06-01")
    assert article["readingTimeMinutes"] >= 1


def test_explicit_title_overrides_the_generic_one():
    _, article = _brief_to_article(SAMPLE_BRIEF, "2026-06-01", title="BTC Loses $73K Handle")
    assert article["title"] == "BTC Loses $73K Handle"
    assert article["schema"]["headline"] == "BTC Loses $73K Handle"


# ---------------------------------------------------------------------------
# Headline fallback
# ---------------------------------------------------------------------------

def test_lead_signal_extraction():
    lead = _extract_lead_signal(SAMPLE_BRIEF)
    assert lead.startswith("OP's disappearance from the trending board")
    assert "**" not in lead


def test_lead_signal_absent_returns_empty():
    assert _extract_lead_signal("## Morning Brief\n\nNothing here.") == ""


# ---------------------------------------------------------------------------
# Plaintext conversion
# ---------------------------------------------------------------------------

def test_plaintext_strips_links_to_their_label():
    assert _md_to_plaintext("See [the report](https://example.com/x).") == "See the report."


def test_plaintext_strips_blockquotes_and_emphasis():
    out = _md_to_plaintext("> **Quoted** and *emphasised* and `code`")
    assert out == "Quoted and emphasised and code"
