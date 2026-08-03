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

# Keyword -> tag. Matched on word boundaries: a substring match here would tag
# every brief containing "whether" as ethereum and "console" as solana.
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

# Assets we can entity-link in schema.org `about`. Entity linking is a strong
# ranking signal for finance content and we already know which assets a brief
# covers, so it costs nothing to emit.
_ASSET_ENTITIES: dict[str, dict[str, Any]] = {
    "bitcoin": {
        "name": "Bitcoin",
        "keywords": ("bitcoin", "btc"),
        "sameAs": [
            "https://en.wikipedia.org/wiki/Bitcoin",
            "https://www.coingecko.com/en/coins/bitcoin",
        ],
    },
    "ethereum": {
        "name": "Ethereum",
        "keywords": ("ethereum", "eth"),
        "sameAs": [
            "https://en.wikipedia.org/wiki/Ethereum",
            "https://www.coingecko.com/en/coins/ethereum",
        ],
    },
    "solana": {
        "name": "Solana",
        "keywords": ("solana", "sol"),
        "sameAs": [
            "https://en.wikipedia.org/wiki/Solana_(blockchain_platform)",
            "https://www.coingecko.com/en/coins/solana",
        ],
    },
}

# Meta descriptions are truncated by search engines beyond ~160 characters.
SUMMARY_MAX_CHARS = 160
# X/Twitter allows 280; leave room for the date prefix and a trailing link.
TWEET_MAX_CHARS = 200
# Google News rejects `headline` values longer than 110 characters.
SCHEMA_HEADLINE_MAX_CHARS = 110
# SERP titles are truncated around 60 characters.
TITLE_MAX_CHARS = 60

_WORDS_PER_MINUTE = 225

# "1. OVERNIGHT MOVES", "OPEN QUESTION" \u2014 a section label, never prose.
_SECTION_LABEL_RE = re.compile(r'^\s*(?:\d+\.\s*)?[A-Z][A-Z0-9\s&/\'-]{2,}$')


def _word_match(keyword: str, text_lower: str) -> bool:
    """Whole-word (not substring) keyword match."""
    return re.search(rf'(?<!\w){re.escape(keyword)}(?!\w)', text_lower) is not None


def _word_count_of(keyword: str, text_lower: str) -> int:
    return len(re.findall(rf'(?<!\w){re.escape(keyword)}(?!\w)', text_lower))


def _md_to_plaintext(md: str) -> str:
    """Strip markdown formatting to produce plain prose.

    Used only for the summary, tweet and word count \u2014 never for the published
    body, which keeps its heading structure (see `_prepare_article_body`).
    """
    text = re.sub(r'^#{1,6}\s+', '', md, flags=re.MULTILINE)
    text = re.sub(r'^\s*>\s?', '', text, flags=re.MULTILINE)          # blockquotes
    text = re.sub(r'!\[([^\]]*)\]\([^)]*\)', r'\1', text)             # images
    text = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', text)              # links -> label
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'`(.+?)`', r'\1', text)
    text = re.sub(r'^---+$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*[-*+]\s+', '', text, flags=re.MULTILINE)      # bullet lists
    text = re.sub(r'^\s*\d+\.\s+(?=[a-z])', '', text, flags=re.MULTILINE)  # ordered lists
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def _truncate_at_boundary(text: str, limit: int) -> str:
    """Truncate to `limit` chars without cutting mid-word.

    Prefers ending on a sentence boundary if one falls in the last third of the
    allowance, otherwise falls back to the last whole word plus an ellipsis.
    """
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    window = text[:limit]
    sentence_end = max(window.rfind(". "), window.rfind("! "), window.rfind("? "))
    if sentence_end >= limit * 0.6:
        return window[: sentence_end + 1].strip()
    word_end = window.rfind(" ")
    if word_end <= 0:
        return window.rstrip()
    return window[:word_end].rstrip(" ,;:\u2014-") + "\u2026"


def _is_section_label(paragraph: str) -> bool:
    """True for headings like '1. OVERNIGHT MOVES' that survive plaintexting."""
    return bool(_SECTION_LABEL_RE.match(paragraph.strip()))


def _first_prose_paragraph(plain: str) -> str:
    """First real paragraph of prose, skipping the title line and section labels.

    The previous implementation blindly took `paragraphs[1]`, which is always the
    first section heading \u2014 every published article's meta description read
    "1. OVERNIGHT MOVES".
    """
    paragraphs = [p.strip() for p in plain.split("\n\n") if p.strip()]
    for i, para in enumerate(paragraphs):
        if _is_section_label(para):
            continue
        if i == 0 and para.lower().startswith("morning brief"):
            continue  # duplicate of the title
        if len(para) < 80 and not re.search(r'[.!?]', para):
            continue  # stray label or fragment
        return para
    return paragraphs[0] if paragraphs else ""


def _titleize_heading(heading: str) -> str:
    """'1. OVERNIGHT MOVES' -> 'Overnight Moves'. Leaves mixed-case headings alone."""
    text = re.sub(r'^\s*\d+\.\s*', '', heading).strip()
    if text.isupper():
        return text.title()
    return text


def _prepare_article_body(md: str) -> str:
    """Publish-ready markdown: H2 sections, no duplicate title line.

    The body used to be flattened to plaintext before publishing, which stripped
    every heading and list from the article \u2014 nothing left for passage indexing,
    jump links or snippet extraction.
    """
    lines = md.splitlines()
    out: list[str] = []
    seen_first_heading = False
    for line in lines:
        match = re.match(r'^(#{1,6})\s+(.*)$', line)
        if not match:
            out.append(line)
            continue
        level, text = len(match.group(1)), match.group(2)
        if not seen_first_heading and level <= 2 and text.lower().startswith("morning brief"):
            # Duplicates the page <h1>; drop it rather than emit two H1-ish nodes.
            seen_first_heading = True
            continue
        seen_first_heading = True
        out.append(f"## {_titleize_heading(text)}" if level >= 2 else f"# {_titleize_heading(text)}")
    return re.sub(r'\n{3,}', '\n\n', "\n".join(out)).strip()


def _detect_assets(content: str) -> list[str]:
    """Assets discussed in the brief, in a stable order."""
    lower = content.lower()
    return [
        meta["name"]
        for meta in _ASSET_ENTITIES.values()
        if any(_word_match(kw, lower) for kw in meta["keywords"])
    ]


def _extract_tags(text_lower: str) -> list[str]:
    tags: set[str] = {"morning-brief", "market-analysis", "research"}
    for kw, tag in _KNOWN_TAGS.items():
        if _word_match(kw, text_lower):
            tags.add(tag)
    return sorted(tags)[:8]


def _pick_category(text_lower: str) -> str:
    btc = _word_count_of("bitcoin", text_lower) + _word_count_of("btc", text_lower)
    eth = _word_count_of("ethereum", text_lower) + _word_count_of("eth", text_lower)
    if btc > eth * 2:
        return "bitcoin"
    if eth > btc * 2:
        return "ethereum"
    return "general"


def _make_image_prompt(brief_content: str) -> str:
    """Craft a Chroma image generation prompt for the morning brief header."""
    assets = _detect_assets(brief_content)
    asset_str = " and ".join(assets[:2]) if assets else "cryptocurrency"
    return (
        f"Professional crypto research newsletter header art. Abstract visualization of {asset_str} "
        "market data: luminous price charts and candlestick graphs, blockchain network topology, "
        "flowing financial data streams. Deep navy and black background with electric blue and "
        "amber gold neon accent lighting. No text, no words, no numbers, no letters anywhere. "
        "High-end editorial illustration, cinematic wide-angle composition, ultra detailed."
    )


def _make_image_alt(brief_content: str, date_fmt: str) -> str:
    """Descriptive alt text \u2014 required for image SEO and accessibility."""
    assets = _detect_assets(brief_content)
    asset_str = ", ".join(assets[:3]) if assets else "cryptocurrency"
    return (
        f"Abstract editorial illustration of {asset_str} price charts and blockchain "
        f"network data, header art for the crypto research morning brief of {date_fmt}."
    )


def _extract_lead_signal(content: str) -> str:
    """First sentence of the 'SIGNAL NOT TO MISS' section, if present.

    Deterministic fallback for headline generation when Venice is unavailable.
    """
    match = re.search(
        r'#{1,6}\s*(?:\d+\.\s*)?SIGNAL NOT TO MISS\s*\n(.+?)(?=\n#{1,6}\s|\Z)',
        content,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return ""
    body = _md_to_plaintext(match.group(1)).strip()
    first = re.split(r'(?<=[.!?])\s+', body)[0] if body else ""
    return first.strip()


async def _generate_headline(content: str, date_fmt: str) -> str:
    """Ask Venice for an SEO headline describing the day's lead signal.

    Every brief previously shipped the same title with only the date changed,
    so six near-identical articles competed with each other and carried no query
    intent. Falls back to a deterministic extraction, then to the generic title.
    """
    generic = f"Crypto Research Morning Brief \u2014 {date_fmt}"
    try:
        raw = await venice.chat_complete(
            [
                {
                    "role": "system",
                    "content": (
                        "You write search-optimised news headlines. Reply with the headline "
                        "only \u2014 no quotes, no markdown, no trailing punctuation."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Write one headline of at most {TITLE_MAX_CHARS} characters for this "
                        "crypto morning brief. Name the specific asset or narrative and what "
                        "happened. No dates, no colons, no clickbait.\n\n"
                        f"{content[:4000]}"
                    ),
                },
            ],
            web_search=False,
            temperature=0.3,
            max_tokens=60,
        )
        headline = _md_to_plaintext(raw or "").strip().strip('"\u201c\u201d').rstrip(".")
        headline = " ".join(headline.split())
        if 15 <= len(headline) <= TITLE_MAX_CHARS * 2:
            return _truncate_at_boundary(headline, TITLE_MAX_CHARS)
        log.warning("Headline rejected (length %d): %r", len(headline), headline)
    except Exception as exc:
        log.warning("Headline generation failed, using fallback: %s", exc)

    lead = _extract_lead_signal(content)
    if len(lead) >= 15:
        return _truncate_at_boundary(lead, TITLE_MAX_CHARS)
    return generic


def _previous_brief_slug(date_str: str) -> str | None:
    """Slug of the most recent brief before `date_str`, for prev/next linking."""
    try:
        dates = sorted(
            f["name"].replace("brief-", "")
            for f in vault.list_vault_files("00-Inbox")
            if f["name"].startswith("brief-")
        )
    except Exception:
        return None
    earlier = [d for d in dates if d < date_str]
    return f"{earlier[-1]}-crypto-research-morning-brief" if earlier else None


def _build_schema(
    *,
    article: dict,
    canonical_url: str,
    image_url: str | None,
    image_alt: str,
    word_count: int,
    assets: list[str],
) -> dict:
    """schema.org NewsArticle graph for the published page."""
    cfg = get_settings()
    schema: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "AnalysisNewsArticle",
        "headline": _truncate_at_boundary(article["title"], SCHEMA_HEADLINE_MAX_CHARS),
        "description": article["summary"],
        "datePublished": article["publishedAt"],
        "dateModified": article["dateModified"],
        "author": {"@type": "Organization", "name": cfg.author_name, "url": cfg.author_url},
        "publisher": {
            "@type": "Organization",
            "name": cfg.publisher_name,
            "logo": {"@type": "ImageObject", "url": cfg.publisher_logo_url},
        },
        "mainEntityOfPage": {"@type": "WebPage", "@id": canonical_url},
        "articleSection": article["category"],
        "keywords": article["tags"],
        "inLanguage": "en",
        "isAccessibleForFree": True,
        "wordCount": word_count,
        "disclaimer": cfg.disclaimer,
    }
    if image_url:
        schema["image"] = {
            "@type": "ImageObject",
            "url": image_url,
            "caption": image_alt,
            "width": 1280,
            "height": 720,
        }
    if assets:
        schema["about"] = [
            {
                "@type": "Thing",
                "name": meta["name"],
                "sameAs": meta["sameAs"],
            }
            for meta in _ASSET_ENTITIES.values()
            if meta["name"] in assets
        ]
    return schema


def _brief_to_article(content: str, date_str: str, title: str | None = None) -> tuple[str, dict]:
    """Convert a markdown brief into the cryptocatalyst.news article payload.

    Returns (slug, article_dict).
    """
    cfg = get_settings()
    plain = _md_to_plaintext(content)
    text_lower = plain.lower()

    summary = _truncate_at_boundary(_first_prose_paragraph(plain), SUMMARY_MAX_CHARS)
    date_fmt = datetime.strptime(date_str, "%Y-%m-%d").strftime("%B %d, %Y")
    slug = f"{date_str}-crypto-research-morning-brief"
    canonical_url = cfg.article_url(slug)
    now_iso = datetime.now(tz=timezone.utc).isoformat()
    body_md = _prepare_article_body(content)
    word_count = len(plain.split())
    image_alt = _make_image_alt(content, date_fmt)
    assets = _detect_assets(content)

    article: dict = {
        "slug": slug,
        "title": title or f"Crypto Research Morning Brief \u2014 {date_fmt}",
        "summary": summary,
        # `body` is now markdown rather than flattened plaintext so the published
        # article keeps its H2 sections and lists. `bodyHtml`/`bodyText` are
        # provided so a consumer expecting either form still has one.
        "body": body_md,
        "bodyFormat": "markdown",
        "bodyHtml": _markdown_to_html(body_md),
        "bodyText": plain,
        "canonicalUrl": canonical_url,
        "sourceUrl": canonical_url,
        "sourceName": "Crypto Research Autopilot",
        "author": cfg.author_name,
        "category": _pick_category(text_lower),
        "tags": _extract_tags(text_lower),
        "publishedAt": now_iso,
        "dateModified": now_iso,
        "language": "en",
        "wordCount": word_count,
        "readingTimeMinutes": max(1, round(word_count / _WORDS_PER_MINUTE)),
        "disclaimer": cfg.disclaimer,
        "imageUrl": None,
        "imageAlt": image_alt,
        "previousSlug": _previous_brief_slug(date_str),
        "twitterThread": [],
        "standaloneTweet": _truncate_at_boundary(
            f"Crypto morning brief, {date_fmt}: {summary}", TWEET_MAX_CHARS
        ),
    }
    article["schema"] = _build_schema(
        article=article,
        canonical_url=canonical_url,
        image_url=None,
        image_alt=image_alt,
        word_count=word_count,
        assets=assets,
    )
    return slug, article


def _attach_image(article: dict, image_path: str) -> None:
    """Set the article image, absolutising the URL for og:image and schema.org."""
    cfg = get_settings()
    absolute = image_path if image_path.startswith("http") else f"{cfg.site_url}{image_path}"
    article["imageUrl"] = absolute
    article["schema"]["image"] = {
        "@type": "ImageObject",
        "url": absolute,
        "caption": article["imageAlt"],
        "width": 1280,
        "height": 720,
    }


def _markdown_to_html(md: str) -> str:
    """Render publish-ready markdown to HTML. Returns '' if rendering fails."""
    try:
        import markdown as md_lib

        return md_lib.markdown(md, extensions=["extra", "sane_lists"])
    except Exception as exc:  # pragma: no cover \u2014 optional dependency path
        log.warning("Markdown -> HTML rendering skipped: %s", exc)
        return ""


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

def _as_number(value: Any) -> float | None:
    """Coerce to float, or None. Guards every f-string numeric format below."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_global_market(data: dict) -> str:
    """Format CoinGecko /global data.

    CoinGecko nests values as `total_market_cap.usd`; the CoinMarketCap-style
    `quote.USD.*` lookup this used to do silently dropped market cap and volume
    from every brief.
    """
    if not data:
        return "No global market data available."
    lines = []
    cap = _as_number(data.get("total_market_cap", {}).get("usd"))
    if cap is not None:
        lines.append(f"Total market cap: ${cap:,.0f}")
    btc_dom = _as_number(data.get("market_cap_percentage", {}).get("btc"))
    if btc_dom is not None:
        lines.append(f"BTC dominance: {btc_dom:.1f}%")
    eth_dom = _as_number(data.get("market_cap_percentage", {}).get("eth"))
    if eth_dom is not None:
        lines.append(f"ETH dominance: {eth_dom:.1f}%")
    vol = _as_number(data.get("total_volume", {}).get("usd"))
    if vol is not None:
        lines.append(f"24h volume: ${vol:,.0f}")
    cap_change = _as_number(data.get("market_cap_change_percentage_24h_usd"))
    if cap_change is not None:
        lines.append(f"Total market cap 24h change: {cap_change:+.2f}%")
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
        symbol = token.get("symbol", cg_id).upper()
        price = _as_number(p.get("usd"))
        # A single coin missing a USD quote used to raise ValueError and take
        # down the whole scheduled run.
        price_str = f"${price:,.4f}" if price is not None else "price unavailable"
        chg = _as_number(p.get("usd_24h_change"))
        chg_str = f" ({chg:+.1f}%)" if chg is not None else ""
        lines.append(f"  {symbol}: {price_str}{chg_str}")
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
        # `.get(key, default)` does not fire when the key exists with value None,
        # so these must be coerced before formatting.
        cmc_btc = _as_number(cm.get("btc_dominance"))
        cmc_eth = _as_number(cm.get("eth_dominance"))
        cmc_lines = []
        if cmc_btc is not None:
            cmc_lines.append(f"BTC dominance: {cmc_btc:.1f}%")
        if cmc_eth is not None:
            cmc_lines.append(f"ETH dominance: {cmc_eth:.1f}%")
        if cmc_lines:
            market_section += "\n\n### CMC Global Metrics\n" + " | ".join(cmc_lines)

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
            from app.services.github_publisher import push_brief

            date_fmt = datetime.strptime(date_str, "%Y-%m-%d").strftime("%B %d, %Y")
            headline = await _generate_headline(content, date_fmt)
            slug, article = _brief_to_article(content, date_str, title=headline)

            # Generate header image with Venice Chroma
            image_bytes: bytes | None = None
            try:
                img_prompt = _make_image_prompt(content)
                image_bytes = await venice.generate_image(img_prompt)
                _attach_image(article, f"/images/articles/{slug}.webp")
                log.info("Brief image generated: %s", article["imageUrl"])
            except Exception as img_exc:
                log.warning("Image generation skipped: %s", img_exc)

            # Article (and image, if generated) are pushed together in one
            # commit so publishing a brief triggers a single Vercel deploy.
            await push_brief(
                token=settings.github_token,
                repo=settings.github_repo,
                slug=slug,
                article=article,
                image_bytes=image_bytes,
                commit_message=f"\U0001f4ca Morning Brief: {date_str}",
            )
            published_url = settings.article_url(slug)
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
    price = _as_number(market_data.get("current_price", {}).get("usd"))
    market_cap = _as_number(market_data.get("market_cap", {}).get("usd"))
    change_24h = _as_number(market_data.get("price_change_percentage_24h"))
    desc = (coin_detail.get("description") or {}).get("en", "")[:800]

    if coin_detail:
        live_snippet = "\n".join([
            f"Current price: ${price:,.4f}" if price is not None else "Current price: unavailable",
            f"Market cap: ${market_cap:,.0f}" if market_cap is not None else "Market cap: unavailable",
            f"24h change: {change_24h:+.2f}%" if change_24h is not None else "24h change: unavailable",
            f"Description: {desc}",
        ])
    else:
        live_snippet = "No live data available — research manually."

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
