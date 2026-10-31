"""
news.py — keyless news sources used by the terminal engine.

This is the small, auditable subset of the former chat module: yfinance news,
GDELT and the public RSS feeds.  It performs no AI-chat or LLM calls and reads
no environment variables.  Every host contacted here is documented in
SKILL.md (Network access).
"""
from __future__ import annotations

import re
import time
from datetime import datetime

import requests


def _yf_news_items(symbol: str, limit: int = 15) -> list:
    """yfinance news normalised to the legacy schema.

    Keys: title, publisher, link, providerPublishTime.

    ``Ticker.news`` is empty for many symbols on newer yfinance builds, so fall
    back to ``Search.news`` (which still returns the legacy shape). Items using
    the newer ``content`` shape are normalised to the same keys.
    """
    import yfinance as yf
    raw = []
    try:
        raw = yf.Ticker(symbol).news or []
    except Exception:
        raw = []
    if not raw:
        try:
            raw = yf.Search(symbol).news or []
        except Exception:
            raw = []
    out = []
    for n in raw:
        if not isinstance(n, dict):
            continue
        c = n.get('content') if isinstance(n.get('content'), dict) else None
        if c:
            prov = c.get('provider') if isinstance(c.get('provider'), dict) else {}
            canon = c.get('canonicalUrl') if isinstance(c.get('canonicalUrl'), dict) else {}
            click = c.get('clickThroughUrl') if isinstance(c.get('clickThroughUrl'), dict) else {}
            ts, pd = 0, c.get('pubDate') or c.get('displayTime') or ''
            if pd:
                try:
                    ts = int(datetime.fromisoformat(str(pd).replace('Z', '+00:00')).timestamp())
                except Exception:
                    ts = 0
            out.append({'title': c.get('title', ''),
                        'publisher': prov.get('displayName') or c.get('publisher', ''),
                        'providerPublishTime': ts,
                        'link': canon.get('url') or click.get('url') or ''})
        else:
            out.append(n)
    return out[:limit]


def _news_yfinance_fallback(query: str, category: str = '') -> dict:
    """yfinance RSS news for a ticker or market-wide (SPY proxy)."""
    tickers = re.findall(r'\b([A-Z]{1,5})\b', query.upper())
    syms = tickers[:2] if tickers else ['SPY', 'QQQ']
    try:
        seen, items = set(), []
        for sym in syms:
            for n in _yf_news_items(sym, limit=8):
                t = n.get('title', '')
                if t and t not in seen:
                    seen.add(t)
                    ts = n.get('providerPublishTime', 0)
                    dt = datetime.fromtimestamp(ts).strftime('%Y-%m-%d') if ts else ''
                    items.append({'title': t, 'source': n.get('publisher', 'yfinance'),
                                  'date': dt, 'url': n.get('link', ''), 'snippet': ''})
        return {'query': query, 'source': 'yfinance (RSS)',
                'article_count': len(items), 'articles': items}
    except Exception as e:
        raise ValueError(f"yfinance news failed: {e}")


_gdelt_last_call: float = 0


def _gdelt_fetch_with_retry(url: str, params: dict, max_retries: int = 3) -> requests.Response | None:
    global _gdelt_last_call
    for attempt in range(max_retries):
        elapsed = time.time() - _gdelt_last_call
        if elapsed < 6:
            time.sleep(6 - elapsed)
        _gdelt_last_call = time.time()
        try:
            r = requests.get(url, params=params, timeout=30)
            if r.status_code == 429:
                time.sleep(6)
                continue
            r.raise_for_status()
            return r
        except requests.exceptions.Timeout:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            return None
        except requests.exceptions.RequestException:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            return None
    return None


def _news_gdelt(query: str, category: str = '') -> dict:
    """GDELT 2.0 Doc API — free, no key, global news coverage with tone/sentiment."""
    q = query or 'finance markets economy'
    r = _gdelt_fetch_with_retry(
        'https://api.gdeltproject.org/api/v2/doc/doc',
        {'query': f'{q} sourcelang:english sourcecountry:US',
         'format': 'json', 'maxrecords': 10, 'mode': 'artlist'},
    )
    if r is None:
        return _news_yfinance_fallback(query) if query else _news_yfinance_fallback('finance markets economy')
    articles = r.json().get('articles', []) or r.json().get('results', [])
    items = []
    for a in articles[:10]:
        title = a.get('title') or a.get('seentitle', '')
        if not title:
            continue
        items.append({
            'title':   title,
            'source':  a.get('domain', 'GDELT'),
            'date':    (a.get('seendate') or '')[:10],
            'url':     a.get('url', ''),
            'snippet': (a.get('sentence', '') or '')[:300],
        })
    return {'query': query, 'source': 'GDELT',
            'article_count': len(items), 'articles': items}


# ─── NEWS (RSS Feeds — free, no key) ─────────────────────────────────────────

FINANCIAL_RSS_FEEDS = [
    ('https://feeds.content.dowjones.io/public/rss/mw_top_stories', 'MarketWatch'),
    ('https://feeds.content.dowjones.io/public/rss/mw_market_pulse', 'MarketWatch'),
    ('https://www.investopedia.com/feedbuilder/feed/getfeed?feedName=rss_feed', 'Investopedia'),
    ('https://feeds.bloomberg.com/markets/news.rss', 'Bloomberg'),
    ('https://www.cnbc.com/id/100003114/device/rss/rss.html', 'CNBC'),
    ('https://www.zerohedge.com/rss.xml', 'ZeroHedge'),
    ('https://seekingalpha.com/feed.xml', 'Seeking Alpha'),
    ('https://feeds.npr.org/1001/rss.xml', 'NPR'),
    ('https://rss.nytimes.com/services/xml/rss/nyt/Business.xml', 'NYT Business'),
    ('https://feeds.bbci.co.uk/news/business/rss.xml', 'BBC Business'),
    ('https://www.wsj.com/xml/rss/3_7085.xml', 'WSJ'),
    ('https://finance.yahoo.com/news/rssindex', 'Yahoo Finance'),
    ('https://www.economist.com/feeds/print-sections/77/business.xml', 'Economist'),
]


def _news_rss(query: str, category: str = '') -> dict:
    """Aggregate financial news from RSS feeds, filtered by optional query."""
    import feedparser
    q_lower = query.lower() if query else ''
    seen, items = set(), []
    for feed_url, feed_name in FINANCIAL_RSS_FEEDS:
        try:
            f = feedparser.parse(feed_url)
            for entry in f.entries[:8]:
                title = entry.get('title', '')
                if not title:
                    continue
                if q_lower and not (q_lower in title.lower()
                                    or any(kw in title.lower() for kw in q_lower.split())):
                    continue
                if title in seen:
                    continue
                seen.add(title)
                link = entry.get('link', '')
                pub = entry.get('published', '') or entry.get('updated', '')
                items.append({
                    'title':   title,
                    'source':  feed_name,
                    'date':    pub[:10] if len(pub) >= 10 else '',
                    'url':     link,
                    'snippet': (entry.get('summary', '') or '')[:200],
                })
                if len(items) >= 10:
                    break
        except Exception:
            continue
        if len(items) >= 10:
            break
    return {'query': query, 'source': 'RSS Feeds',
            'article_count': len(items), 'articles': items[:10]}
