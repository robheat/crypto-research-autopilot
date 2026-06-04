"""Morning brief orchestrator.

Flow:
1. Read vault context (theses, narratives, watchlist notes, recent inbox)
2. Fetch live market data (CoinGecko always; CMC + LunarCrush if keys present)
3. Optionally augment with Venice web search for latest crypto news
4. Build a rich prompt and call Venice API
5. Save the brief to vault/00-Inbox/brief-YYYY-MM-DD.md
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from app.config import get_settings
from app.services import coingecko, coinmarketcap, lunarcrush, vault, venice

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Article formatting helpers
# ---------------------------------------------------------------------------

_KNOWN_TAGS: dict[str, str] = {
    "bitcoin": "bitcoin", "btc": "bitcoin",
    "ethereum": "ethereum", "eth": "ethereum",
    "defi": "defi", "solana": "solana", "sol": "solana",
    "stablecoin": "stablecoin", "stablecoins": "stablecoin",
    "nft": "nft", "regulation": "regulation", "policy": "policy",
    "on-chain": "on-chain", "onchain": "on-chain",
    "narrative": "narrative", "sentiment": "market-sentiment",
    "institutional": "institutional",
}


def _md_to_plaintext(md: str) -> str:
    """Strip markdown formatting to produce plain prose."""
    text = re.sub(r'^#{1,6}\s+', '', md, flags=re.MULTILINE)
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'`(.+?)`', r'\1', text)
    text = re.sub(r'^---+$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*[-*+]\s+', '', text, flags=re.MULTILINE)
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def _make_image_prompt(brief_content: str) -> str:
    """Craft a Chroma image generation prompt for the morning brief header."""
    lower = brief_content.lower()
    assets = []
    if "bitcoin" in lower or " btc" in lower:
        assets.append("Bitcoin")
    if "ethereum" in lower or " eth" in lower:
        assets.append("Ethereum")
    if "solana" in lower or " sol " in lower:
        assets.append("Solana")
    asset_str = " and ".join(assets[:2]) if assets else "cryptocurrency"
    return (
        f"Professional crypto research newsletter header art. Abstract visualization of {asset_str} "
        "market data: luminous price charts and candlestick graphs, blockchain network topology, "
        "flowing financial data streams. Deep navy and black background with electric blue and "
        "amber gold neon accent lighting. No text, no words, no numbers, no letters anywhere. "
        "High-end editorial illustration, cinematic wide-angle composition, ultra detailed."
    )


def _brief_to_article(content: str, date_str: str) -> tuple[str, dict]:
    """Convert markdown brief to cryptocatalyst.news article JSON.

    Returns (slug, article_dict).
    """
    plain = _md_to_plaintext(content)
    paragraphs = [p.strip() for p in plain.split('\n\n') if p.strip()]
    # Use the second paragraph as summary (first is usually just the title line)
    summary = (paragraphs[1] if len(paragraphs) > 1 else paragraphs[0] if paragraphs else "")[:280]

    text_lower = plain.lower()
    tags: set[str] = {"morning-brief", "market-analysis", "research"}
    for kw, tag in _KNOWN_TAGS.items():
        if kw in text_lower:
            tags.add(tag)

    btc_count = text_lower.count("bitcoin") + text_lower.count(" btc")
    eth_count = text_lower.count("ethereum") + text_lower.count(" eth")
    if btc_count > eth_count * 2:
        category = "bitcoin"
    elif eth_count > btc_count * 2:
        category = "ethereum"
    else:
        category = "general"

    date_fmt = datetime.strptime(date_str, "%Y-%m-%d").strftime("%B %d, %Y")
    slug = f"{date_str}-crypto-research-morning-brief"

    article: dict = {
        "slug": slug,
        "title": f"Crypto Research Morning Brief \u2014 {date_fmt}",
        "summary": summary,
        "body": plain,
        "sourceUrl": "https://cryptocatalyst.news",
        "sourceName": "Crypto Research Autopilot",
        "category": category,
        "tags": sorted(list(tags))[:8],
        "publishedAt": datetime.now(tz=timezone.utc).isoformat(),
        "imageUrl": None,
        "twitterThread": [],
        "standaloneTweet": f"Daily crypto research brief for {date_fmt}: {summary[:200]}",
    }
    return slug, article


# ---------------------------------------------------------------------------
# Live data aggregation
# ---------------------------------------------------------------------------

async def _fetch_coingecko(watchlist_ids: list[str]) -> dict[str, Any]:
    tasks = [
        coingecko.get_global_market(),
        coingecko.get_trending(),
    ]
    if watchlist_ids:
        tasks.append(coingecko.get_prices(watchlist_ids))
    else:
        tasks.append(asyncio.sleep(0))  # placeholder

    results = await asyncio.gather(*tasks, return_exceptions=True)
    global_data = results[0] if not isinstance(results[0], Exception) else {}
    trending = results[1] if not isinstance(results[1], Exception) else []
    prices = results[2] if (watchlist_ids and not isinstance(results[2], Exception)) else {}

    return {"global": global_data, "trending": trending, "prices": prices}


async def _fetch_cmc(api_key: str) -> dict[str, Any]:
    tasks = [
        coinmarketcap.get_fear_and_greed(api_key),
        coinmarketcap.get_global_metrics(api_key),
    ]
    results = await asyncio.gather(*tasks)
    return {"fear_greed": results[0], "global": results[1]}


async def _fetch_lunarcrush(api_key: str, symbols: list[str]) -> dict[str, Any]:
    tasks: list = [lunarcrush.get_trending_topics(api_key)]
    for sym in symbols[:5]:  # limit to avoid rate limits
        tasks.append(lunarcrush.get_coin_sentiment(api_key, sym))
    results = await asyncio.gather(*tasks, return_exceptions=True)
    topics = results[0] if not isinstance(results[0], Exception) else []
    sentiments = [r for r in results[1:] if r and not isinstance(r, Exception)]
    return {"topics": topics, "sentiments": sentiments}


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------

def _format_global_market(data: dict) -> str:
    if not data:
        return "No global market data available."
    lines = []
    if "total_market_cap" in data.get("quote", {}).get("USD", {}):
        cap = data["quote"]["USD"]["total_market_cap"]
        lines.append(f"Total market cap: ${cap:,.0f}")
    btc_dom = data.get("market_cap_percentage", {}).get("btc")
    if btc_dom:
        lines.append(f"BTC dominance: {btc_dom:.1f}%")
    vol = data.get("quote", {}).get("USD", {}).get("total_volume_24h")
    if vol:
        lines.append(f"24h volume: ${vol:,.0f}")
    return "\n".join(lines) if lines else "Global market data available (no structured fields parsed)."


def _format_prices(prices: dict, watchlist: list[dict]) -> str:
    if not prices:
        return "No watchlist price data available."
    lines = []
    for token in watchlist:
        cg_id = token.get("coingecko_id")
        if not cg_id or cg_id not in prices:
            continue
        p = prices[cg_id]
        price = p.get("usd", "N/A")
        chg = p.get("usd_24h_change")
        chg_str = f" ({chg:+.1f}%)" if chg is not None else ""
        symbol = token.get("symbol", cg_id).upper()
        lines.append(f"  {symbol}: ${price:,.4f}{chg_str}")
    return "\n".join(lines) if lines else "No price data found for watchlist tokens."


def _format_trending(trending: list) -> str:
    if not trending:
        return "No trending data available."
    lines = []
    for item in trending[:7]:
        coin = item.get("item", item)
        name = coin.get("name", "?")
        symbol = coin.get("symbol", "?")
        lines.append(f"  {name} ({symbol})")
    return "\n".join(lines)


def _build_brief_prompt(
    system_context: str,
    vault_context: str,
    live_data: dict,
) -> list[dict]:
    settings = get_settings()
    cg = live_data.get("coingecko", {})
    cmc = live_data.get("cmc", {})
    lc = live_data.get("lunarcrush", {})
    watchlist = live_data.get("watchlist_tokens", [])
    today = datetime.now(tz=timezone.utc).strftime("%A, %B %d, %Y")

    market_section = f"""## Live Market Data — {today}

### CoinGecko Global
{_format_global_market(cg.get("global", {}))}

### Watchlist Prices (24h)
{_format_prices(cg.get("prices", {}), watchlist)}

### Trending on CoinGecko (24h)
{_format_trending(cg.get("trending", []))}"""

    if cmc.get("fear_greed"):
        fg = cmc["fear_greed"]
        market_section += f"\n\n### Fear & Greed Index\nValue: {fg.get('value')} — {fg.get('sentiment')}"

    if cmc.get("global"):
        cm = cmc["global"]
        market_section += (
            f"\n\n### CMC Global Metrics"
            f"\nBTC dominance: {cm.get('btc_dominance', 'N/A'):.1f}%"
            f" | ETH dominance: {cm.get('eth_dominance', 'N/A'):.1f}%"
        )

    if lc.get("topics"):
        topics_str = "\n".join(
            f"  {t['topic']} — {t.get('interactions_24h', 0):,} interactions (24h)"
            for t in (lc.get("topics") or [])[:8]
        )
        market_section += f"\n\n### LunarCrush Trending Topics\n{topics_str}"

    if lc.get("sentiments"):
        sent_lines = []
        for s in lc["sentiments"]:
            if s:
                sent_lines.append(
                    f"  {s['symbol']}: Galaxy Score {s.get('galaxy_score', 'N/A')}"
                    f" | Sentiment {s.get('sentiment', 'N/A')}"
                    f" | Social Vol 24h {s.get('social_volume_24h', 'N/A')}"
                )
        if sent_lines:
            market_section += "\n\n### LunarCrush Watchlist Sentiment\n" + "\n".join(sent_lines)

    prompt = f"""{system_context}

---

{vault_context}

---

{market_section}

---

You have read the research vault and the live market data above.

Produce today's morning brief written for an audience of experienced crypto traders and researchers. Write in a direct, newsletter style — no "your" or "my", no second-person. Address the market and the reader as a community. Use "traders", "the market", "watch", "worth noting" — not "you should" or "your thesis".

Use EXACTLY this structure:

## Morning Brief — {today}

### 1. OVERNIGHT MOVES
[Material price action, volume spikes, or on-chain events across the watchlist. Only flag what is significant. If nothing is material, say so clearly. Write for traders who scan this in 60 seconds.]

### 2. NARRATIVE PULSE
[Shifts in social sentiment or emerging narrative momentum. What is building that most of the market has not noticed yet?]

### 3. THESIS CHECK
[Does today's live data support or contradict the active theses in the vault? Quote thesis note text directly when flagging a conflict or confirmation. Frame it as signal for traders holding these positions.]

### 4. SIGNAL NOT TO MISS
[The single most important piece of information from across all sources today. One clear, specific statement.]

### 5. OPEN QUESTION
[One question the market should be sitting with. Not a task. A question worth thinking about.]

Be direct. No padding. Every sentence earns its place. No second-person."""

    return [
        {"role": "system", "content": "You are a professional crypto research analyst writing a daily morning brief for an audience of experienced traders and researchers. Write in a clear, direct newsletter style. Never use second-person ('you', 'your'). Refer to 'traders', 'the market', 'the watchlist'. Every sentence must carry specific signal — no generic commentary."},
        {"role": "user", "content": prompt},
    ]


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def generate_brief(web_search: bool = True) -> dict[str, str]:
    """Generate a morning brief and save it to the vault. Returns path + content."""
    settings = get_settings()

    # 1. Read vault context
    system_context, theses_ctx, narratives_ctx, watchlist_ctx, inbox_ctx = await asyncio.gather(
        vault.read_file("04-Intelligence/SYSTEM.md"),
        vault.read_section("01-Market/theses"),
        vault.read_section("01-Market/narratives"),
        vault.read_section("01-Market/watchlist"),
        vault.read_recent_inbox(24),
        return_exceptions=True,
    )

    def _safe(val: Any, fallback: str = "") -> str:
        return val if isinstance(val, str) else fallback

    system_context = _safe(system_context)
    vault_context = "\n\n".join(filter(None, [
        "## My Active Theses\n\n" + _safe(theses_ctx) if _safe(theses_ctx) else "",
        "## Narratives I Am Tracking\n\n" + _safe(narratives_ctx) if _safe(narratives_ctx) else "",
        "## My Watchlist Notes\n\n" + _safe(watchlist_ctx) if _safe(watchlist_ctx) else "",
        "## Recent Captures (last 24h)\n\n" + _safe(inbox_ctx) if _safe(inbox_ctx) else "",
    ])) or "Vault is empty — this is the first brief."

    # 2. Fetch live data
    watchlist_tokens = vault.get_watchlist()
    watchlist_ids = vault.get_watchlist_coingecko_ids()
    watchlist_symbols = vault.get_watchlist_symbols()

    cg_task = _fetch_coingecko(watchlist_ids)
    cmc_task = _fetch_cmc(settings.cmc_api_key) if settings.cmc_api_key else asyncio.sleep(0)
    lc_task = (
        _fetch_lunarcrush(settings.lunarcrush_api_key, watchlist_symbols)
        if settings.lunarcrush_api_key
        else asyncio.sleep(0)
    )

    cg_data, cmc_data, lc_data = await asyncio.gather(cg_task, cmc_task, lc_task)
    cg_data = cg_data if isinstance(cg_data, dict) else {}
    cmc_data = cmc_data if isinstance(cmc_data, dict) else {}
    lc_data = lc_data if isinstance(lc_data, dict) else {}

    live_data = {
        "coingecko": cg_data,
        "cmc": cmc_data,
        "lunarcrush": lc_data,
        "watchlist_tokens": watchlist_tokens,
    }

    # 3. Build prompt and call Venice
    messages = _build_brief_prompt(system_context, vault_context, live_data)
    content = await venice.chat_complete(
        messages,
        web_search=web_search,
        temperature=0.5,
        max_tokens=3000,
    )

    # 4. Save to vault
    date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    filename = f"00-Inbox/brief-{date_str}.md"
    await vault.write_file(filename, content)

    # 5. Publish to cryptocatalyst.news if GitHub token is configured
    published_url: str | None = None
    if settings.github_token and settings.github_repo:
        try:
            from app.services.github_publisher import push_article, push_image
            slug, article = _brief_to_article(content, date_str)

            # Generate header image with Venice Chroma
            try:
                img_prompt = _make_image_prompt(content)
                img_bytes = await venice.generate_image(img_prompt)
                image_url = await push_image(
                    token=settings.github_token,
                    repo=settings.github_repo,
                    slug=slug,
                    image_bytes=img_bytes,
                    commit_message=f"\U0001f5bc\ufe0f Brief image: {date_str}",
                )
                article["imageUrl"] = image_url
                log.info("Brief image uploaded: %s", image_url)
            except Exception as img_exc:
                log.warning("Image generation skipped: %s", img_exc)

            await push_article(
                token=settings.github_token,
                repo=settings.github_repo,
                slug=slug,
                article=article,
                commit_message=f"\U0001f4ca Morning Brief: {date_str}",
            )
            published_url = f"https://cryptocatalyst.news/articles/{slug}"
            log.info("Brief published to %s", published_url)
        except Exception as exc:
            log.warning("GitHub publish failed: %s", exc)

    return {"path": filename, "content": content, "date": date_str, "published_url": published_url}


async def generate_token_research(
    token_name: str,
    symbol: str,
    coingecko_id: str = "",
    custom_notes: str = "",
) -> dict[str, str]:
    """Generate a structured token research note using Venice."""
    today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

    # Fetch live data for this token
    coin_detail: dict = {}
    if coingecko_id:
        try:
            coin_detail = await coingecko.get_coin_detail(coingecko_id)
        except Exception:
            coin_detail = {}

    market_data = coin_detail.get("market_data", {})
    price = market_data.get("current_price", {}).get("usd", "N/A")
    market_cap = market_data.get("market_cap", {}).get("usd", "N/A")
    change_24h = market_data.get("price_change_percentage_24h", "N/A")
    desc = coin_detail.get("description", {}).get("en", "")[:800]

    live_snippet = f"""Current price: ${price}
Market cap: ${market_cap:,} (if numeric)
24h change: {change_24h}%
Description: {desc}""" if coin_detail else "No live data available — research manually."

    prompt = f"""Generate a structured token research note for {token_name} ({symbol.upper()}) using this EXACT template (fill in every section with real analysis):

# {token_name} ({symbol.upper()}) Research

Last updated: {today}
Status: Watching

## One Line
[What this token does in one sentence — no jargon]

## Why I Am Looking At This
[What signal or thesis brought this to attention — be specific]

## Thesis
[The specific reason this could outperform. Not general — specific to this token's position in the market right now]

## On-Chain Health
[Current TVL, active addresses, transaction volume, any anomalies — use live data below]

## Social Momentum
[Current sentiment trend, any narrative building — 7-day direction]

## What Would Make Me Wrong
[The specific scenario where this thesis fails. Be precise.]

## Open Questions
[What I still do not know that matters]

---
Live data for context:
{live_snippet}

Additional notes from researcher:
{custom_notes or "None provided."}

---
Be precise and analytical. Fill every section with substantive content. No filler."""

    content = await venice.chat_complete(
        [
            {"role": "system", "content": "You are a professional crypto research analyst. Produce precise, structured research notes."},
            {"role": "user", "content": prompt},
        ],
        web_search=True,
        temperature=0.4,
        max_tokens=2000,
    )

    filename = f"02-Research/tokens/{symbol.lower()}-{today}.md"
    await vault.write_file(filename, content)
    return {"path": filename, "content": content}
