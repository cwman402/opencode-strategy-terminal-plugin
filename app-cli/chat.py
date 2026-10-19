"""
chat.py — AI Chat powered by Local LLM / OpenAI with Strategy Terminal tool integration.

Data layer supports FMP, yfinance, and Alpha Vantage with configurable per-tool priority.
Priority is set from the Data Sources admin page and persisted in session state.
"""

import math
import json
import os
import time
import requests
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from datetime import date, timedelta, datetime

# ── Colour palette ─────────────────────────────────────────────────────────────
T = {
    'bg':     '#0a0e1a', 'panel':  '#0f1729', 'border': '#1e2d4a',
    'amber':  '#ffb300', 'green':  '#00c853', 'red':    '#ff1744',
    'blue':   '#1565c0', 'white':  '#e8eaf6', 'muted':  '#546e7a',
}

# ══════════════════════════════════════════════════════════════════════════════
# DATA SOURCE REGISTRY
# ══════════════════════════════════════════════════════════════════════════════

ALL_SOURCES = {
    "fmp":           "FMP (Financial Modeling Prep)",
    "yfinance":      "yfinance (Yahoo Finance)",
    "alpha_vantage": "Alpha Vantage",
    "newsapi":       "NewsAPI",
    "gdelt":         "GDELT (Global News)",
    "rss":           "RSS Feeds (Financial)",
    "finnhub":       "Finnhub",
    "coingecko":     "CoinGecko (Crypto)",
    "worldbank":     "World Bank (Macro)",
}

SOURCE_KEY_FIELD = {
    "fmp":           "fmp",
    "alpha_vantage": "alpha_vantage",
    "newsapi":       "newsapi_key",
    "finnhub":       "finnhub",
    # yfinance, gdelt, rss, coingecko, worldbank need no key
}

# Default per-tool priority — FMP first where it provides richer data
DEFAULT_SOURCE_PRIORITY: dict[str, list[str]] = {
    "overview":  ["fmp", "yfinance", "alpha_vantage"],
    "history":   ["fmp", "yfinance"],
    "sector":    ["fmp", "yfinance"],
    "macro":     ["worldbank", "yfinance", "alpha_vantage"],
    "screener":  ["fmp", "yfinance"],
    "options":   ["yfinance"],
    "search":    ["fmp", "yfinance"],
    "news":      ["newsapi", "gdelt", "rss", "finnhub", "yfinance"],
    "crypto":    ["coingecko", "yfinance"],
}

TOOL_LABELS = {
    "overview": "Stock Overview",
    "history":  "Price History",
    "sector":   "Sector Performance",
    "macro":    "Macro Indicators",
    "screener": "Stock Screener",
    "options":  "Options Summary",
    "search":   "Ticker Search",
    "news":     "News Headlines",
    "crypto":   "Crypto Data",
}

def _get_priority(tool: str) -> list[str]:
    cfg = st.session_state.get('ds_priority', {})
    return cfg.get(tool, DEFAULT_SOURCE_PRIORITY.get(tool, ["yfinance"]))

def _get_keys() -> dict:
    return st.session_state.get('term_api_keys', {})

def _has_key(source: str) -> bool:
    field = SOURCE_KEY_FIELD.get(source)
    if not field:
        return True
    return bool(_get_keys().get(field, '').strip())


# ══════════════════════════════════════════════════════════════════════════════
# PER-SOURCE IMPLEMENTATIONS
# ══════════════════════════════════════════════════════════════════════════════

FMP_BASE = "https://financialmodelingprep.com/api/v3"
AV_BASE  = "https://www.alphavantage.co/query"

def _fmp(endpoint: str, params: dict | None = None) -> dict | list:
    key = _get_keys().get('fmp', '').strip()
    p   = {"apikey": key}
    if params:
        p.update(params)
    r = requests.get(f"{FMP_BASE}/{endpoint}", params=p, timeout=10)
    r.raise_for_status()
    return r.json()

def _yf_safe(ticker: str):
    try:
        import yfinance as yf
        return yf.Ticker(ticker)
    except Exception:
        return None

def _av(params: dict) -> dict:
    key = _get_keys().get('alpha_vantage', '').strip()
    p   = {"apikey": key}
    p.update(params)
    r = requests.get(AV_BASE, params=p, timeout=10)
    r.raise_for_status()
    return r.json()


# ─── OVERVIEW ──────────────────────────────────────────────────────────────────

def _overview_fmp(ticker: str) -> dict:
    profile = _fmp(f"profile/{ticker}")
    quote   = _fmp(f"quote/{ticker}")
    if not profile or not quote:
        raise ValueError("Empty FMP response")
    p = profile[0] if isinstance(profile, list) else profile
    q = quote[0]   if isinstance(quote,   list) else quote
    chg_pct = q.get('changesPercentage')
    return {
        "ticker":       ticker.upper(), "source": "FMP",
        "name":         p.get('companyName', ''),
        "sector":       p.get('sector', ''),
        "industry":     p.get('industry', ''),
        "price":        q.get('price'),
        "prev_close":   q.get('previousClose'),
        "change_pct":   round(float(chg_pct), 2) if chg_pct else None,
        "market_cap":   p.get('mktCap'),
        "pe_ttm":       q.get('pe'),
        "eps_ttm":      q.get('eps'),
        "beta":         p.get('beta'),
        "52w_high":     q.get('yearHigh'),
        "52w_low":      q.get('yearLow'),
        "div_yield":    p.get('lastDiv'),
        "volume":       q.get('volume'),
        "avg_volume":   q.get('avgVolume'),
        "open":         q.get('open'),
        "day_high":     q.get('dayHigh'),
        "day_low":      q.get('dayLow'),
        "50d_avg":      q.get('priceAvg50'),
        "200d_avg":     q.get('priceAvg200'),
        "shares_out":   q.get('sharesOutstanding'),
        "exchange":     p.get('exchangeShortName', ''),
        "description":  (p.get('description') or '')[:300],
        "ceo":          p.get('ceo', ''),
        "employees":    p.get('fullTimeEmployees'),
        "website":      p.get('website', ''),
    }

def _overview_yf(ticker: str) -> dict:
    t = _yf_safe(ticker)
    if not t:
        raise ValueError(f"yfinance: no ticker {ticker}")
    info = t.info
    fi   = t.fast_info
    spot = getattr(fi, 'last_price', None) or info.get('currentPrice')
    prev = getattr(fi, 'previous_close', None) or info.get('previousClose')
    chg  = ((spot - prev) / prev * 100) if spot and prev and float(prev) > 0 else None
    return {
        "ticker":         ticker.upper(), "source": "yfinance",
        "name":           info.get('shortName') or info.get('longName', ''),
        "sector":         info.get('sector', ''),
        "industry":       info.get('industry', ''),
        "price":          round(float(spot), 4) if spot else None,
        "prev_close":     round(float(prev), 4) if prev else None,
        "change_pct":     round(chg, 2) if chg is not None else None,
        "market_cap":     info.get('marketCap'),
        "pe_ttm":         info.get('trailingPE'),
        "fwd_pe":         info.get('forwardPE'),
        "pb":             info.get('priceToBook'),
        "ev_ebitda":      info.get('enterpriseToEbitda'),
        "eps_ttm":        info.get('trailingEps'),
        "revenue_ttm":    info.get('totalRevenue'),
        "gross_margin":   info.get('grossMargins'),
        "net_margin":     info.get('profitMargins'),
        "roe":            info.get('returnOnEquity'),
        "debt_equity":    info.get('debtToEquity'),
        "beta":           info.get('beta'),
        "52w_high":       info.get('fiftyTwoWeekHigh'),
        "52w_low":        info.get('fiftyTwoWeekLow'),
        "div_yield":      info.get('dividendYield'),
        "analyst_target": info.get('targetMeanPrice'),
        "analyst_rating": info.get('recommendationKey'),
    }

def _overview_av(ticker: str) -> dict:
    d = _av({"function": "OVERVIEW", "symbol": ticker})
    if not d or "Symbol" not in d:
        raise ValueError("AV: no overview data")
    def _f(k): return float(d[k]) if d.get(k) not in (None, 'None', '-', '') else None
    return {
        "ticker": ticker.upper(), "source": "Alpha Vantage",
        "name": d.get('Name', ''), "sector": d.get('Sector', ''),
        "industry": d.get('Industry', ''),
        "market_cap": _f('MarketCapitalization'),
        "pe_ttm":     _f('TrailingPE'), "fwd_pe":  _f('ForwardPE'),
        "pb":         _f('PriceToBookRatio'), "ev_ebitda": _f('EVToEBITDA'),
        "eps_ttm":    _f('EPS'), "gross_margin": _f('GrossProfitTTM'),
        "net_margin": _f('ProfitMargin'), "roe": _f('ReturnOnEquityTTM'),
        "beta":       _f('Beta'), "52w_high": _f('52WeekHigh'),
        "52w_low":    _f('52WeekLow'), "div_yield": _f('DividendYield'),
        "analyst_target": _f('AnalystTargetPrice'),
    }


# ─── HISTORY ───────────────────────────────────────────────────────────────────

def _history_fmp(ticker: str, period: str) -> dict:
    days_map = {"1mo": 30, "3mo": 90, "6mo": 180, "1y": 365, "2y": 730, "5y": 1825}
    from_dt  = (date.today() - timedelta(days=days_map.get(period, 365))).isoformat()
    data     = _fmp(f"historical-price-full/{ticker}", {"from": from_dt})
    hist     = data.get("historical", []) if isinstance(data, dict) else []
    if not hist:
        raise ValueError("FMP: empty history")
    hist.sort(key=lambda x: x['date'])
    closes   = [float(h['close']) for h in hist]
    rets     = [closes[i]/closes[i-1]-1 for i in range(1, len(closes))]
    ann      = math.sqrt(252)
    rv21     = float(np.std(rets[-21:])  * ann * 100) if len(rets) >= 21 else None
    rv63     = float(np.std(rets[-63:])  * ann * 100) if len(rets) >= 63 else None
    tot_ret  = (closes[-1] / closes[0] - 1) * 100
    return {
        "ticker": ticker.upper(), "source": "FMP", "period": period,
        "start_date": hist[0]['date'],  "end_date": hist[-1]['date'],
        "start_price": round(closes[0], 4), "end_price": round(closes[-1], 4),
        "total_return_pct": round(tot_ret, 2),
        "max_price": round(max(float(h['high']) for h in hist), 4),
        "min_price": round(min(float(h['low'])  for h in hist), 4),
        "rv21_pct":  round(rv21, 2) if rv21 else None,
        "rv63_pct":  round(rv63, 2) if rv63 else None,
        "avg_volume": int(sum(h.get('volume', 0) for h in hist) / len(hist)),
        "trading_days": len(hist),
        "recent_closes": [round(c, 2) for c in closes[-5:]],
    }

def _history_yf(ticker: str, period: str) -> dict:
    t = _yf_safe(ticker)
    if not t:
        raise ValueError(f"yfinance: no ticker {ticker}")
    df = t.history(period=period, interval='1d', auto_adjust=True)
    if df.empty:
        raise ValueError("yfinance: empty history")
    rets    = df['Close'].pct_change().dropna()
    ann     = math.sqrt(252)
    rv21    = float(rets.tail(21).std() * ann * 100)
    rv63    = float(rets.tail(63).std() * ann * 100) if len(rets) >= 63 else None
    tot_ret = (df['Close'].iloc[-1] / df['Close'].iloc[0] - 1) * 100
    return {
        "ticker": ticker.upper(), "source": "yfinance", "period": period,
        "start_date": str(df.index[0].date()), "end_date": str(df.index[-1].date()),
        "start_price": round(float(df['Close'].iloc[0]), 4),
        "end_price":   round(float(df['Close'].iloc[-1]), 4),
        "total_return_pct": round(float(tot_ret), 2),
        "max_price":   round(float(df['High'].max()), 4),
        "min_price":   round(float(df['Low'].min()), 4),
        "rv21_pct":    round(rv21, 2),
        "rv63_pct":    round(rv63, 2) if rv63 else None,
        "avg_volume":  int(df['Volume'].mean()),
        "trading_days": len(df),
        "recent_closes": [round(float(v), 2) for v in df['Close'].tail(5).tolist()],
    }


# ─── SECTOR ────────────────────────────────────────────────────────────────────

def _sector_fmp() -> dict:
    data = _fmp("sectors-performance")
    rows = []
    for s in (data if isinstance(data, list) else []):
        try:
            chg = float(str(s.get('changesPercentage', '0')).replace('%', ''))
        except Exception:
            chg = 0.0
        rows.append({"sector": s.get('sector', ''), "etf": '', "day_chg_pct": round(chg, 2)})
    rows.sort(key=lambda x: x['day_chg_pct'], reverse=True)
    return {"sectors": rows, "source": "FMP"}

def _sector_yf() -> dict:
    import yfinance as yf
    sectors = [
        ('XLK','Technology'), ('XLF','Financials'), ('XLV','Healthcare'),
        ('XLE','Energy'), ('XLI','Industrials'), ('XLY','Consumer Disc'),
        ('XLP','Consumer Staples'), ('XLB','Materials'), ('XLRE','Real Estate'),
        ('XLU','Utilities'), ('XLC','Communication'),
    ]
    rows = []
    for sym, name in sectors:
        try:
            fi   = yf.Ticker(sym).fast_info
            last = getattr(fi, 'last_price', None)
            prev = getattr(fi, 'previous_close', None)
            if last and prev and float(prev) > 0:
                chg = (float(last) - float(prev)) / float(prev) * 100
                rows.append({"sector": name, "etf": sym,
                             "price": round(float(last), 2), "day_chg_pct": round(chg, 2)})
        except Exception:
            pass
    rows.sort(key=lambda x: x.get('day_chg_pct', 0), reverse=True)
    return {"sectors": rows, "source": "yfinance"}


# ─── SCREENER ──────────────────────────────────────────────────────────────────

def _screener_fmp(min_mc: float, max_pe: float, min_beta: float, max_beta: float) -> dict:
    data = _fmp("stock-screener", {
        "marketCapMoreThan": int(min_mc * 1e9),
        "betaMoreThan": min_beta, "betaLowerThan": max_beta,
        "limit": 50, "exchange": "NYSE,NASDAQ",
    })
    matched = []
    for s in (data if isinstance(data, list) else []):
        pe_raw = s.get('pe')
        pe = float(pe_raw) if pe_raw else None
        if pe and pe > max_pe:
            continue
        matched.append({
            "symbol": s.get('symbol', ''), "name": (s.get('companyName') or '')[:30],
            "price": s.get('price'), "sector": s.get('sector', ''),
            "market_cap_b": round(float(s.get('marketCap') or 0) / 1e9, 1),
            "pe": round(pe, 1) if pe else None, "beta": s.get('beta'),
        })
    return {"filters": {"min_mktcap_b": min_mc, "max_pe": max_pe,
                        "min_beta": min_beta, "max_beta": max_beta},
            "source": "FMP", "count": len(matched), "stocks": matched}

def _screener_yf(min_mc: float, max_pe: float, min_beta: float, max_beta: float) -> dict:
    import yfinance as yf
    universe = ['AAPL','MSFT','AMZN','GOOG','META','NVDA','TSLA','JPM','JNJ',
                'V','PG','MA','UNH','XOM','HD','CVX','MRK','LLY','ABBV','KO',
                'PEP','AVGO','COST','MCD','TMO','ACN','WMT','ABT','CRM','ORCL',
                'NFLX','AMD','INTC','QCOM','TXN','AMGN','GS','MS','BAC']
    matched = []
    for sym in universe:
        try:
            info = yf.Ticker(sym).info
            mc   = info.get('marketCap') or 0
            pe   = info.get('trailingPE')
            beta = info.get('beta')
            if mc < min_mc * 1e9: continue
            if pe and float(pe) > max_pe: continue
            if beta and not (min_beta <= float(beta) <= max_beta): continue
            matched.append({
                "symbol": sym, "name": (info.get('shortName') or '')[:30],
                "price": round(float(info.get('currentPrice') or 0), 2),
                "market_cap_b": round(mc / 1e9, 1),
                "pe": round(float(pe), 1) if pe else None,
                "beta": round(float(beta), 2) if beta else None,
            })
        except Exception:
            continue
    return {"filters": {"min_mktcap_b": min_mc, "max_pe": max_pe,
                        "min_beta": min_beta, "max_beta": max_beta},
            "source": "yfinance", "count": len(matched), "stocks": matched}


# ─── SEARCH ────────────────────────────────────────────────────────────────────

def _search_fmp(query: str) -> dict:
    data    = _fmp("search", {"query": query, "limit": 8})
    results = [
        {"symbol": s.get('symbol',''), "name": (s.get('name') or '')[:50],
         "type": s.get('stockExchange',''), "exchange": s.get('exchangeShortName','')}
        for s in (data if isinstance(data, list) else []) if s.get('symbol')
    ]
    return {"query": query, "source": "FMP", "results": results[:8]}

def _search_yf(query: str) -> dict:
    resp = requests.get(
        "https://query2.finance.yahoo.com/v1/finance/search",
        params={'q': query, 'quotesCount': 8, 'newsCount': 0, 'enableFuzzyQuery': True},
        headers={'User-Agent': 'Mozilla/5.0'}, timeout=6,
    )
    keep    = {'EQUITY', 'ETF', 'INDEX'}
    results = [
        {"symbol": q.get('symbol',''),
         "name": (q.get('shortname') or q.get('longname') or '')[:50],
         "type": q.get('quoteType',''), "exchange": q.get('exchDisp') or q.get('exchange','')}
        for q in resp.json().get('quotes', []) if q.get('quoteType','').upper() in keep
    ]
    return {"query": query, "source": "yfinance", "results": results}


# ─── OPTIONS ───────────────────────────────────────────────────────────────────

def _options_yf(ticker: str) -> dict:
    t = _yf_safe(ticker)
    if not t:
        raise ValueError(f"yfinance: no ticker {ticker}")
    dates = t.options
    if not dates:
        raise ValueError("No options data")
    info  = t.info
    spot  = info.get('currentPrice') or info.get('regularMarketPrice', 0)
    iv    = info.get('impliedVolatility')
    chain = t.option_chain(dates[0])
    atm_c = chain.calls[(chain.calls['strike'] - spot).abs() < spot * 0.03].head(3)
    atm_p = chain.puts [(chain.puts['strike']  - spot).abs() < spot * 0.03].head(3)
    return {
        "ticker": ticker.upper(), "source": "yfinance",
        "spot": round(float(spot), 2) if spot else None,
        "iv_30d": round(float(iv) * 100, 2) if iv else None,
        "expiries": list(dates[:5]), "nearest_expiry": dates[0],
        "atm_calls": atm_c[['strike','lastPrice','impliedVolatility',
                             'volume','openInterest']].to_dict('records'),
        "atm_puts":  atm_p[['strike','lastPrice','impliedVolatility',
                             'volume','openInterest']].to_dict('records'),
    }



# ─── NEWS (NewsAPI — primary; yfinance RSS fallback) ───────────────────────────

def _news_newsapi(query: str, category: str = '') -> dict:
    """NewsAPI /v2/everything or /v2/top-headlines."""
    key = _get_keys().get('newsapi_key', '').strip()
    if not key:
        raise ValueError("No NewsAPI key configured")
    base    = 'https://newsapi.org/v2'
    headers = {'X-Api-Key': key}
    NA_CATS = {'business', 'technology', 'science', 'health', 'general'}

    if category and category.lower() in NA_CATS:
        params = {'category': category.lower(), 'language': 'en', 'pageSize': 10}
        r = requests.get(f'{base}/top-headlines', headers=headers,
                         params=params, timeout=10)
    else:
        q = query or 'finance OR markets OR economy'
        params = {'q': q, 'language': 'en', 'sortBy': 'publishedAt', 'pageSize': 10}
        r = requests.get(f'{base}/everything', headers=headers,
                         params=params, timeout=10)
    r.raise_for_status()
    articles = r.json().get('articles', [])
    items = [
        {
            'title':   a.get('title', ''),
            'source':  (a.get('source') or {}).get('name', ''),
            'date':    (a.get('publishedAt') or '')[:10],
            'url':     a.get('url', ''),
            'snippet': (a.get('description') or '')[:200],
        }
        for a in articles
        if a.get('title') and a.get('title') != '[Removed]'
    ]
    return {'query': query or category, 'source': 'NewsAPI',
            'article_count': len(items), 'articles': items[:10]}


def _news_yfinance_fallback(query: str, category: str = '') -> dict:
    """yfinance RSS news for a ticker or market-wide (SPY proxy)."""
    import re as _re2
    tickers = _re2.findall(r'\b([A-Z]{1,5})\b', query.upper())
    syms    = tickers[:2] if tickers else ['SPY', 'QQQ']
    try:
        import yfinance as yf
        seen, items = set(), []
        for sym in syms:
            for n in (yf.Ticker(sym).news or [])[:8]:
                t = n.get('title', '')
                if t and t not in seen:
                    seen.add(t)
                    ts  = n.get('providerPublishTime', 0)
                    dt  = datetime.fromtimestamp(ts).strftime('%Y-%m-%d') if ts else ''
                    items.append({'title': t, 'source': n.get('publisher', 'yfinance'),
                                  'date': dt, 'url': n.get('link', ''), 'snippet': ''})
        return {'query': query, 'source': 'yfinance (RSS)',
                'article_count': len(items), 'articles': items}
    except Exception as e:
        raise ValueError(f"yfinance news failed: {e}")


# ─── NEWS (GDELT — free, no key required) ────────────────────────────────────

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
        {'query': f'{q} sourcelang:english sourcecountry:US', 'format': 'json', 'maxrecords': 10, 'mode': 'artlist'},
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
    import re as _re_rss
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
                pub  = entry.get('published', '') or entry.get('updated', '')
                # Extract source from feed name or entry
                src = feed_name
                items.append({
                    'title':   title,
                    'source':  src,
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


# ─── NEWS (Finnhub — requires free API key) ──────────────────────────────────

def _news_finnhub(query: str, category: str = '') -> dict:
    """Finnhub market news / company news."""
    key = _get_keys().get('finnhub', '').strip()
    if not key:
        raise ValueError("No Finnhub key configured")
    import re as _re_fh
    tickers = _re_fh.findall(r'\b([A-Z]{1,5})\b', query.upper())
    if tickers:
        params = {'symbol': tickers[0], 'from': (date.today() - timedelta(days=7)).isoformat(),
                  'to': date.today().isoformat(), 'token': key}
        r = requests.get('https://finnhub.io/api/v1/company-news',
                         params=params, timeout=8)
    else:
        q = query or 'finance'
        params = {'category': 'general', 'minId': 0, 'token': key}
        r = requests.get('https://finnhub.io/api/v1/news',
                         params=params, timeout=8)
    r.raise_for_status()
    articles = r.json() if isinstance(r.json(), list) else []
    items = [{
        'title':   a.get('headline', ''),
        'source':  a.get('source', 'Finnhub'),
        'date':    datetime.fromtimestamp(a['datetime']).strftime('%Y-%m-%d')
                   if a.get('datetime') else '',
        'url':     a.get('url', ''),
        'snippet': (a.get('summary', '') or '')[:200],
    } for a in articles[:10] if a.get('headline')]
    return {'query': query, 'source': 'Finnhub',
            'article_count': len(items), 'articles': items}


# ─── NEWS (dispatch — tries multiple sources in priority order) ──────────────

def tool_get_news(query: str = '', category: str = '') -> dict:
    """
    Fetch latest news headlines. Tries sources in configured priority order:
    NewsAPI → GDELT → RSS Feeds → Finnhub → yfinance fallback.
    query    – free-text topic or ticker e.g. "Apple earnings", "NVDA", "interest rates"
    category – NewsAPI category: business | technology | science | general
    """
    return _dispatch("news", query, category)


# ─── MACRO ─────────────────────────────────────────────────────────────────────

def _macro_fred(indicator: str) -> dict:
    FRED_MAP = {
        'GDP':'GDP','CPI':'CPIAUCSL','INFLATION':'CPIAUCSL','UNRATE':'UNRATE',
        'UNEMPLOYMENT':'UNRATE','FEDFUNDS':'FEDFUNDS','DGS10':'DGS10','DGS2':'DGS2',
        'M2':'M2SL','INDPRO':'INDPRO','RETAIL':'RSAFS',
    }
    sid = FRED_MAP.get(indicator.upper(), indicator.upper())
    r   = requests.get(
        f"https://api.stlouisfed.org/fred/series/observations"
        f"?series_id={sid}&limit=5&sort_order=desc&file_type=json", timeout=8)
    obs = r.json().get('observations', [])
    if not obs:
        raise ValueError(f"FRED: no data for {sid}")
    return {
        "series_id": sid, "indicator": indicator.upper(), "source": "FRED",
        "latest_value": obs[0].get('value'), "latest_date": obs[0].get('date'),
        "prev_value":   obs[1].get('value') if len(obs) > 1 else None,
        "prev_date":    obs[1].get('date')  if len(obs) > 1 else None,
    }

def _macro_av(indicator: str) -> dict:
    AV_FUNC = {
        'CPI':'CPI','INFLATION':'INFLATION','UNRATE':'UNEMPLOYMENT',
        'GDP':'REAL_GDP','FEDFUNDS':'FEDERAL_FUNDS_RATE','RETAIL':'RETAIL_SALES',
    }
    func = AV_FUNC.get(indicator.upper())
    if not func:
        raise ValueError(f"AV: no mapping for {indicator}")
    d    = _av({"function": func})
    data = d.get('data', [])
    if not data:
        raise ValueError("AV: empty macro data")
    return {
        "series_id": func, "indicator": indicator.upper(), "source": "Alpha Vantage",
        "latest_value": data[0].get('value'), "latest_date": data[0].get('date'),
        "prev_value": data[1].get('value') if len(data) > 1 else None,
        "prev_date":  data[1].get('date')  if len(data) > 1 else None,
    }


# ─── CRYPTO (CoinGecko — free, no key) ────────────────────────────────────────

def _crypto_coingecko(query: str) -> dict:
    """CoinGecko API — crypto prices, market data, trending coins."""
    q = query.lower().strip()
    # Try to find specific coin
    coin_map = {
        'bitcoin': 'bitcoin', 'btc': 'bitcoin',
        'ethereum': 'ethereum', 'eth': 'ethereum',
        'solana': 'solana', 'sol': 'solana',
        'cardano': 'cardano', 'ada': 'cardano',
        'ripple': 'ripple', 'xrp': 'ripple',
        'dogecoin': 'dogecoin', 'doge': 'dogecoin',
        'polkadot': 'polkadot', 'dot': 'polkadot',
        'avalanche': 'avalanche-2', 'avax': 'avalanche-2',
        'chainlink': 'chainlink', 'link': 'chainlink',
        'polygon': 'matic-network', 'matic': 'matic-network',
        'uniswap': 'uniswap', 'uni': 'uniswap',
        'litecoin': 'litecoin', 'ltc': 'litecoin',
        'bitcoin-cash': 'bitcoin-cash', 'bch': 'bitcoin-cash',
        'stellar': 'stellar', 'xlm': 'stellar',
        'cosmos': 'cosmos', 'atom': 'cosmos',
        'monero': 'monero', 'xmr': 'monero',
        'ethereum-classic': 'ethereum-classic', 'etc': 'ethereum-classic',
        'filecoin': 'filecoin', 'fil': 'filecoin',
        'aptos': 'aptos', 'apt': 'aptos',
        'sui': 'sui',
        'arbitrum': 'arbitrum', 'arb': 'arbitrum',
        'optimism': 'optimism', 'op': 'optimism',
        'near': 'near', 'near-protocol': 'near',
        'tron': 'tron', 'trx': 'tron',
    }
    coin_id = coin_map.get(q)

    if coin_id:
        r = requests.get(
            f'https://api.coingecko.com/api/v3/coins/{coin_id}',
            params={'localization': 'false', 'tickers': 'false',
                    'community_data': 'false', 'developer_data': 'false'},
            timeout=8,
        )
        r.raise_for_status()
        d = r.json()
        md = d.get('market_data', {})
        return {
            'query': query, 'source': 'CoinGecko',
            'name': d.get('name', ''), 'symbol': d.get('symbol', '').upper(),
            'price': md.get('current_price', {}).get('usd'),
            'market_cap': md.get('market_cap', {}).get('usd'),
            'volume_24h': md.get('total_volume', {}).get('usd'),
            'change_24h_pct': md.get('price_change_percentage_24h'),
            'change_7d_pct': md.get('price_change_percentage_7d'),
            'change_30d_pct': md.get('price_change_percentage_30d'),
            'high_24h': md.get('high_24h', {}).get('usd'),
            'low_24h': md.get('low_24h', {}).get('usd'),
            'circulating_supply': md.get('circulating_supply'),
            'total_supply': md.get('total_supply'),
            'ath': md.get('ath', {}).get('usd'),
            'ath_date': md.get('ath_date', {}).get('usd', ''),
        }
    # Trending / market overview
    r = requests.get('https://api.coingecko.com/api/v3/coins/markets',
                     params={'vs_currency': 'usd', 'order': 'market_cap_desc',
                             'per_page': 10, 'page': 1, 'sparkline': 'false'},
                     timeout=8)
    r.raise_for_status()
    coins = r.json()
    items = [{
        'name': c.get('name', ''), 'symbol': c.get('symbol', '').upper(),
        'price': c.get('current_price'),
        'market_cap': c.get('market_cap'),
        'change_24h_pct': c.get('price_change_percentage_24h'),
        'volume_24h': c.get('total_volume'),
    } for c in coins]
    return {'query': query, 'source': 'CoinGecko', 'top_coins': items,
            'type': 'market_overview' if not coin_id else 'specific_coin'}


# ─── CRYPTO (yfinance fallback) ──────────────────────────────────────────────

def _crypto_yf(query: str) -> dict:
    """yfinance fallback for crypto prices via crypto ETFs or direct tickers."""
    import yfinance as yf
    crypto_map = {
        'bitcoin': 'BTC-USD', 'btc': 'BTC-USD', 'ethereum': 'ETH-USD', 'eth': 'ETH-USD',
        'solana': 'SOL-USD', 'sol': 'SOL-USD', 'dogecoin': 'DOGE-USD', 'doge': 'DOGE-USD',
        'ripple': 'XRP-USD', 'xrp': 'XRP-USD', 'cardano': 'ADA-USD', 'ada': 'ADA-USD',
        'polkadot': 'DOT-USD', 'dot': 'DOT-USD', 'avalanche': 'AVAX-USD', 'avax': 'AVAX-USD',
        'chainlink': 'LINK-USD', 'link': 'LINK-USD', 'polygon': 'MATIC-USD', 'matic': 'MATIC-USD',
        'litecoin': 'LTC-USD', 'ltc': 'LTC-USD', 'bitcoin-cash': 'BCH-USD', 'bch': 'BCH-USD',
        'stellar': 'XLM-USD', 'xlm': 'XLM-USD', 'tron': 'TRX-USD', 'trx': 'TRX-USD',
        'ethereum-classic': 'ETC-USD', 'etc': 'ETC-USD', 'monero': 'XMR-USD', 'xmr': 'XMR-USD',
        'cosmos': 'ATOM-USD', 'atom': 'ATOM-USD', 'near': 'NEAR-USD', 'near-protocol': 'NEAR-USD',
        'aptos': 'APT-USD', 'apt': 'APT-USD', 'sui': 'SUI-USD', 'arbitrum': 'ARB-USD', 'arb': 'ARB-USD',
        'optimism': 'OP-USD', 'op': 'OP-USD', 'filecoin': 'FIL-USD', 'fil': 'FIL-USD',
    }
    q = query.lower().strip()
    ticker = crypto_map.get(q)
    if not ticker:
        ticker = 'BTC-USD'
    t = yf.Ticker(ticker)
    info = t.fast_info
    spot = getattr(info, 'last_price', None)
    hist = t.history(period='7d', interval='1d')
    chg_24h = None
    if spot and not hist.empty and len(hist) > 1:
        prev = hist['Close'].iloc[-2]
        chg_24h = (spot - prev) / prev * 100
    return {
        'query': query, 'source': 'yfinance',
        'price': round(float(spot), 4) if spot else None,
        'change_24h_pct': round(float(chg_24h), 2) if chg_24h else None,
        'ticker': ticker,
    }


# ─── MACRO (World Bank — free, no key) ───────────────────────────────────────

def _macro_worldbank(indicator: str) -> dict:
    """World Bank API for global economic indicators."""
    WB_MAP = {
        'GDP':          'NY.GDP.MKTP.CD',
        'GDP_GROWTH':   'NY.GDP.MKTP.KD.ZG',
        'INFLATION':    'FP.CPI.TOTL.ZG',
        'CPI':          'FP.CPI.TOTL',
        'UNEMPLOYMENT': 'SL.UEM.TOTL.ZS',
        'POPULATION':   'SP.POP.TOTL',
        'EXPORTS':      'NE.EXP.GNFS.ZS',
        'IMPORTS':      'NE.IMP.GNFS.ZS',
        'GDP_PER_CAP':  'NY.GDP.PCAP.CD',
    }
    code = WB_MAP.get(indicator.upper())
    if not code:
        raise ValueError(f"World Bank: unknown indicator {indicator}")
    url = f'http://api.worldbank.org/v2/country/US/indicator/{code}'
    r = requests.get(url, params={'format': 'json', 'per_page': 5, 'date': '2020:2030'},
                     timeout=10)
    r.raise_for_status()
    data = r.json()
    if not data or len(data) < 2:
        raise ValueError("World Bank: empty response")
    obs = [o for o in data[1] if o.get('value') is not None][:5]
    if not obs:
        raise ValueError(f"World Bank: no data for {indicator}")
    return {
        "series_id": code, "indicator": indicator.upper(), "source": "World Bank",
        "latest_value": obs[0].get('value'), "latest_date": obs[0].get('date'),
        "prev_value":   obs[1].get('value') if len(obs) > 1 else None,
        "prev_date":    obs[1].get('date')  if len(obs) > 1 else None,
        "country": "United States",
    }


# ══════════════════════════════════════════════════════════════════════════════
# PRIORITY DISPATCHER
# ══════════════════════════════════════════════════════════════════════════════

_SOURCE_IMPLS: dict[str, dict] = {
    "overview": {"fmp": _overview_fmp, "yfinance": _overview_yf, "alpha_vantage": _overview_av},
    "history":  {"fmp": _history_fmp,  "yfinance": _history_yf},
    "sector":   {"fmp": _sector_fmp,   "yfinance": _sector_yf},
    "screener": {"fmp": _screener_fmp, "yfinance": _screener_yf},
    "search":   {"fmp": _search_fmp,   "yfinance": _search_yf},
    "options":  {"yfinance": _options_yf},
    "macro":    {"worldbank": _macro_worldbank, "yfinance": _macro_fred, "alpha_vantage": _macro_av},
    "news":     {"newsapi": _news_newsapi, "gdelt": _news_gdelt,
                 "rss": _news_rss, "finnhub": _news_finnhub, "yfinance": _news_yfinance_fallback},
    "crypto":   {"coingecko": _crypto_coingecko, "yfinance": _crypto_yf},
}

def _dispatch(tool: str, *args, **kwargs) -> dict:
    """Try each source in priority order, skip those with missing keys, fall back on error."""
    priority = _get_priority(tool)
    impls    = _SOURCE_IMPLS.get(tool, {})
    errors   = {}
    for src in priority:
        if src not in impls:
            continue
        if not _has_key(src):
            errors[src] = "no API key configured"
            continue
        try:
            result = impls[src](*args, **kwargs)
            result["_source_used"] = src
            return result
        except Exception as e:
            errors[src] = str(e)
    return {"error": f"All sources failed: {errors}"}


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC TOOL FUNCTIONS (called by the AI agentic loop)
# ══════════════════════════════════════════════════════════════════════════════

def tool_get_stock_overview(ticker: str) -> dict:
    return _dispatch("overview", ticker)

def tool_get_price_history(ticker: str, period: str = "1y") -> dict:
    return _dispatch("history", ticker, period)

def tool_compare_stocks(tickers: list, period: str = "1y") -> dict:
    results = []
    for tkr in tickers[:6]:
        d = tool_get_price_history(tkr, period)
        if "error" not in d:
            sharpe = ((d["total_return_pct"] / 100) / (d["rv21_pct"] / 100)) \
                     if d.get("rv21_pct") else None
            results.append({
                "ticker":           d["ticker"],
                "total_return_pct": d["total_return_pct"],
                "rv21_pct":         d["rv21_pct"],
                "sharpe_est":       round(sharpe, 2) if sharpe else None,
                "source":           d.get("_source_used", ""),
            })
    return {"comparison": results, "period": period}

def tool_search_ticker(query: str) -> dict:
    return _dispatch("search", query)

def tool_get_sector_performance() -> dict:
    return _dispatch("sector")

def tool_get_macro_data(indicator: str) -> dict:
    # Try FRED first (free, no key), then World Bank, then priority
    try:
        r = _macro_fred(indicator)
        r["_source_used"] = "fred"
        return r
    except Exception:
        pass
    return _dispatch("macro", indicator)


def tool_get_crypto_data(query: str = 'bitcoin') -> dict:
    """
    Fetch cryptocurrency data — price, market cap, 24h/7d/30d change.
    query – coin name e.g. 'bitcoin', 'ethereum', 'solana', or leave empty for top 10.
    """
    return _dispatch("crypto", query)

def tool_screen_stocks(min_mktcap_b: float = 10.0, max_pe: float = 50.0,
                       min_beta: float = 0.0, max_beta: float = 3.0) -> dict:
    return _dispatch("screener", min_mktcap_b, max_pe, min_beta, max_beta)

def tool_get_options_summary(ticker: str) -> dict:
    return _dispatch("options", ticker)


# ══════════════════════════════════════════════════════════════════════════════
# DATA SOURCES ADMIN PAGE
# ══════════════════════════════════════════════════════════════════════════════

def data_sources_page():
    """Admin page to configure per-tool data source priority."""
    ss = st.session_state
    ss.setdefault('ds_priority', {t: list(v) for t, v in DEFAULT_SOURCE_PRIORITY.items()})

    st.markdown("""
<style>
.ds-header {
    background: linear-gradient(90deg, #0f1729 0%, #1e2d4a 100%);
    padding: 10px 18px; border-radius: 8px; margin-bottom: 16px;
    font-family: monospace; color: #ffb300; font-size: 16px;
    font-weight: bold; letter-spacing: 2px;
}
.ds-card {
    background: #0f1729; border: 1px solid #1e2d4a;
    border-radius: 8px; padding: 14px 16px; margin-bottom: 10px;
}
.src-badge {
    display: inline-block; font-family: monospace; font-size: 11px;
    padding: 2px 10px; border-radius: 12px; margin: 2px 4px 2px 0;
}
.src-1  { background: #1b3a1b; color: #00c853; border: 1px solid #00c853; }
.src-2  { background: #1a2a3a; color: #64b5f6; border: 1px solid #64b5f6; }
.src-3  { background: #2a2a1a; color: #ffb300; border: 1px solid #ffb300; }
.src-off{ background: #1a1a1a; color: #546e7a; border: 1px solid #37474f; }
</style>
""", unsafe_allow_html=True)

    st.markdown("<div class='ds-header'>⚙️ &nbsp;DATA SOURCES &nbsp;|&nbsp; "
                "<span style='color:#e8eaf6;font-size:12px'>Priority &amp; Fallback Configuration</span>"
                "</div>", unsafe_allow_html=True)

    keys = _get_keys()

    # ── Key status banner ──────────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    for col, src, field_label in [
        (c1, "fmp",           "FMP"),
        (c2, "yfinance",      "yfinance (free)"),
        (c3, "alpha_vantage", "Alpha Vantage"),
        (c4, "newsapi",       "NewsAPI 📰"),
    ]:
        has = _has_key(src)
        col.markdown(
            f"<div style='background:#0f1729;border:1px solid "
            f"{'#00c853' if has else '#ff1744'};border-radius:6px;"
            f"padding:8px 12px;text-align:center;font-family:monospace;font-size:12px;'>"
            f"{'✅' if has else '⚠️'} <b>{field_label}</b><br>"
            f"<span style='color:#546e7a;font-size:10px'>"
            f"{'Key configured' if has else 'No key — will be skipped'}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

    c5, c6, c7, c8 = st.columns(4)
    for col, src, field_label in [
        (c5, "gdelt",         "GDELT (free)"),
        (c6, "rss",           "RSS Feeds (free)"),
        (c7, "finnhub",       "Finnhub"),
        (c8, "coingecko",     "CoinGecko (free)"),
    ]:
        has = _has_key(src)
        col.markdown(
            f"<div style='background:#0f1729;border:1px solid "
            f"{'#00c853' if has else '#ff1744'};border-radius:6px;"
            f"padding:8px 12px;text-align:center;font-family:monospace;font-size:12px;'>"
            f"{'✅' if has else '⚠️'} <b>{field_label}</b><br>"
            f"<span style='color:#546e7a;font-size:10px'>"
            f"{'Key configured' if has else 'No key — will be skipped'}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

    st.caption("Set API keys in **📟 Terminal → 🔑 API Keys**. "
               "Sources without key icons (GDELT, RSS, CoinGecko, World Bank) "
               "require no API key — free & open. FRED & World Bank tried first for macro. "
               "News falls back through NewsAPI → GDELT → RSS → Finnhub → yfinance.")
    st.markdown("---")

    # ── Per-tool priority editor ────────────────────────────────────────────────
    st.markdown("### 🔀 Priority Order per Tool")
    st.caption("Drag order matters: **#1 is tried first**, fallback to #2, then #3. "
               "Sources with no key are automatically skipped at runtime.")

    changed = False
    for tool, label in TOOL_LABELS.items():
        current = ss.ds_priority.get(tool, list(DEFAULT_SOURCE_PRIORITY.get(tool, [])))
        available_for_tool = list(_SOURCE_IMPLS.get(tool, {}).keys())

        with st.container():
            st.markdown(f"<div class='ds-card'>", unsafe_allow_html=True)
            hc1, hc2 = st.columns([2, 3])
            hc1.markdown(f"**{label}**")

            # Show current priority as coloured badges
            badges = ""
            for i, src in enumerate(current):
                cls   = f"src-{i+1}" if i < 3 else "src-off"
                label_s = ALL_SOURCES.get(src, src)
                no_key  = not _has_key(src)
                badges += (f"<span class='src-badge {cls}'>"
                           f"#{i+1} {label_s}"
                           f"{'  ⚠️no key' if no_key else ''}"
                           f"</span>")
            hc2.markdown(badges, unsafe_allow_html=True)

            # Reorder controls
            cols = st.columns(len(available_for_tool) + 1)
            new_order = []
            for idx, src in enumerate(current):
                if src in available_for_tool:
                    new_order.append(src)

            # Selectboxes to set rank
            rank_cols = st.columns(len(available_for_tool))
            new_priority = list(current)
            for pos, col in enumerate(rank_cols):
                opts  = ["(skip)"] + available_for_tool
                cur_s = current[pos] if pos < len(current) else "(skip)"
                if cur_s not in opts:
                    cur_s = "(skip)"
                sel = col.selectbox(
                    f"#{pos+1}",
                    options=opts,
                    index=opts.index(cur_s),
                    key=f"ds_{tool}_{pos}",
                    label_visibility="visible",
                    format_func=lambda x: "— skip —" if x == "(skip)" else ALL_SOURCES.get(x, x),
                )
                if sel != "(skip)":
                    if pos < len(new_priority):
                        new_priority[pos] = sel
                    else:
                        new_priority.append(sel)

            # Deduplicate, preserve order
            seen      = set()
            deduped   = []
            for s in new_priority:
                if s not in seen and s in available_for_tool:
                    seen.add(s)
                    deduped.append(s)
            # Append any missing available sources as fallbacks
            for s in available_for_tool:
                if s not in seen:
                    deduped.append(s)

            if deduped != ss.ds_priority.get(tool):
                ss.ds_priority[tool] = deduped
                changed = True

            st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("---")

    # ── Reset to defaults ──────────────────────────────────────────────────────
    rc1, rc2 = st.columns([1, 4])
    with rc1:
        if st.button("↩️ Reset to Defaults", key="ds_reset_btn",
                     use_container_width=True):
            ss.ds_priority = {t: list(v) for t, v in DEFAULT_SOURCE_PRIORITY.items()}
            st.success("Reset to defaults.")
            st.rerun()

    # ── Live test panel ────────────────────────────────────────────────────────
    st.markdown("---\n### 🧪 Live Source Test")
    st.caption("Test which source actually responds for a given ticker.")
    tc1, tc2, tc3 = st.columns([2, 1, 1])
    test_ticker = tc1.text_input("Ticker", value="AAPL", key="ds_test_ticker")
    test_tool   = tc2.selectbox("Tool", options=list(TOOL_LABELS.keys()),
                                format_func=lambda x: TOOL_LABELS[x], key="ds_test_tool")
    if tc3.button("▶ Test", key="ds_test_btn", use_container_width=True):
        with st.spinner("Fetching…"):
            if test_tool in ("overview", "history", "search", "options"):
                result = _dispatch(test_tool, test_ticker)
            elif test_tool == "sector":
                result = _dispatch("sector")
            elif test_tool == "screener":
                result = _dispatch("screener", 10.0, 50.0, 0.0, 3.0)
            elif test_tool == "macro":
                result = tool_get_macro_data("CPI")
            else:
                result = {}
        if "error" in result:
            st.error(f"All sources failed: {result['error']}")
        else:
            src_used = result.pop("_source_used", "?")
            st.success(f"✅ Responded via **{ALL_SOURCES.get(src_used, src_used)}**")
            st.json(result)

# TOOL REGISTRY — maps OpenAI function names → Python callables + schemas
# ══════════════════════════════════════════════════════════════════════════════

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_stock_overview",
            "description": (
                "Get live price, key financial stats, valuation multiples, and analyst "
                "consensus for a stock ticker. Use this whenever the user asks about a "
                "specific stock's price, metrics, or fundamentals."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string",
                               "description": "Stock ticker symbol e.g. AAPL, TSLA, NVDA"}
                },
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_price_history",
            "description": (
                "Fetch historical price data, total return, and realised volatility "
                "for a stock over a given period."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                    "period": {
                        "type": "string",
                        "enum": ["1mo", "3mo", "6mo", "1y", "2y", "5y"],
                        "description": "Lookback period (default 1y)",
                    },
                },
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_stocks",
            "description": (
                "Compare total return, volatility and Sharpe ratio across multiple "
                "stocks. Use when the user wants to compare performance."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tickers": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of ticker symbols to compare",
                    },
                    "period": {
                        "type": "string",
                        "enum": ["1mo", "3mo", "6mo", "1y", "2y", "5y"],
                    },
                },
                "required": ["tickers"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_ticker",
            "description": (
                "Search for a stock ticker by company name or partial ticker symbol. "
                "Use when the user mentions a company by name but you need the ticker."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string",
                              "description": "Company name or partial ticker"}
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_sector_performance",
            "description": (
                "Get today's performance across all S&P 500 sectors. "
                "Use when asked about sector rotation or which sectors are up/down."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_macro_data",
            "description": (
                "Fetch a macroeconomic indicator from FRED. "
                "Indicators: GDP, CPI, INFLATION, UNRATE, FEDFUNDS, DGS10, DGS2, M2, "
                "INDPRO, RETAIL."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "indicator": {"type": "string",
                                  "description": "FRED indicator code e.g. GDP, CPI, UNRATE"}
                },
                "required": ["indicator"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "screen_stocks",
            "description": (
                "Screen large-cap US stocks by market cap, P/E ratio, and beta. "
                "Use when the user asks for stock ideas matching certain criteria."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "min_mktcap_b": {"type": "number",
                                     "description": "Min market cap in $B (default 10)"},
                    "max_pe":       {"type": "number",
                                     "description": "Max trailing P/E ratio (default 50)"},
                    "min_beta":     {"type": "number",
                                     "description": "Min beta (default 0)"},
                    "max_beta":     {"type": "number",
                                     "description": "Max beta (default 3)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_options_summary",
            "description": (
                "Get implied volatility and near-term options chain summary for a stock. "
                "Use when asked about options, IV, puts/calls."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"}
                },
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_crypto_data",
            "description": (
                "Fetch cryptocurrency prices, market data, and trending coins. "
                "Use when the user asks about bitcoin, ethereum, solana, or any crypto asset. "
                "Query can be a coin name (bitcoin, ethereum, solana) or empty for top 10 overview."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Coin name e.g. bitcoin, ethereum, solana. Leave empty for top 10.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_news",
            "description": (
                "Fetch the latest news headlines on any financial topic, company, or world event. "
                "ALWAYS call this FIRST when the user asks about news, recent events, what's "
                "happening with a stock or in markets, or anything that could be in today's headlines. "
                "This is the primary news source — use it before any internet search. "
                "Examples: 'news on Apple', 'Fed news today', 'crypto headlines', 'oil prices news'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Free-text search: ticker, company, or topic. "
                            "E.g. 'AAPL earnings', 'Federal Reserve', 'oil OPEC', 'bitcoin'. "
                            "Leave empty for top business headlines."
                        ),
                    },
                    "category": {
                        "type": "string",
                        "enum": ["business", "technology", "science", "health", "general", ""],
                        "description": "Optional category. Use 'business' for market news, 'technology' for tech.",
                    },
                },
            },
        },
    },
]

TOOL_FN_MAP = {
    "get_stock_overview":    tool_get_stock_overview,
    "get_price_history":     tool_get_price_history,
    "compare_stocks":        tool_compare_stocks,
    "search_ticker":         tool_search_ticker,
    "get_sector_performance":tool_get_sector_performance,
    "get_macro_data":        tool_get_macro_data,
    "screen_stocks":         tool_screen_stocks,
    "get_options_summary":   tool_get_options_summary,
    "get_news":              tool_get_news,
    "get_crypto_data":       tool_get_crypto_data,
}

# ── Terminal command suggestions (data tool → visual terminal command) ─────────
TERMINAL_SHORTCUTS = {
    "get_stock_overview":     lambda args: args.get("ticker", ""),
    "get_price_history":      lambda args: f"{args.get('ticker','')} GP {args.get('period','1y')}",
    "compare_stocks":         lambda args: f"{' '.join(args.get('tickers',[])[:4])} COMP" if len(args.get('tickers',[])) > 1 else f"{args.get('tickers',[''])[0]}",
    "get_options_summary":    lambda args: f"{args.get('ticker','')} OPT",
    "get_sector_performance": lambda args: "SECTOR",
    "get_macro_data":         lambda args: f"ECON {args.get('indicator','')}",
    "screen_stocks":          lambda args: "SCREEN",
    "search_ticker":          lambda args: f"SEARCH {args.get('query','')}",
    "get_news":               lambda args: (
        f"NEWS {args.get('query','')}" if args.get('query')
        else f"NEWS {args.get('category','').upper()}" if args.get('category')
        else "NEWS"
    ),
    "get_crypto_data":        lambda args: f"CRYPTO {args.get('query','bitcoin')}",
}

# ══════════════════════════════════════════════════════════════════════════════
# LLM PROVIDERS — Local (Ollama/LM Studio) and OpenAI
# ══════════════════════════════════════════════════════════════════════════════

# Default remote OpenAI-compatible base URL (override in sidebar)
DEFAULT_REMOTE_URL = "http://your-remote-service/v1"

# Default local LLM base URL (Ollama). LM Studio uses port 1234.
DEFAULT_LOCAL_URL  = "http://localhost:11434"

# OpenAI cloud models  (label, model_id, supports_tools)
OPENAI_MODELS = [
    ("GPT-4o",          "gpt-4o",          True),
    ("GPT-4o Mini",     "gpt-4o-mini",     True),
    ("GPT-4 Turbo",     "gpt-4-turbo",     True),
    ("GPT-3.5 Turbo",   "gpt-3.5-turbo",   True),
    ("o1",              "o1",              False),
    ("o1-mini",         "o1-mini",         False),
    ("o3-mini",         "o3-mini",         True),
]
OR_LABELS    = [m[0] for m in OPENAI_MODELS]
OR_IDS       = {m[0]: m[1] for m in OPENAI_MODELS}
OR_HAS_TOOLS = {m[0]: m[2] for m in OPENAI_MODELS}

# Local models whose names suggest tool-calling support
_TOOL_CAPABLE_KEYWORDS = (
    'llama3', 'llama-3', 'qwen2', 'qwen-2', 'mistral', 'mixtral',
    'deepseek', 'gemma', 'phi3', 'phi-3', 'command-r', 'hermes',
    'functionary', 'nexusraven',
)

def _local_model_has_tools(model_name: str) -> bool:
    n = model_name.lower()
    return any(kw in n for kw in _TOOL_CAPABLE_KEYWORDS)


def _discover_local_models(base_url: str) -> list[str]:
    """
    Try Ollama /api/tags first, then OpenAI-compatible /v1/models.
    Returns list of model name strings, empty list on failure.
    """
    base = base_url.rstrip('/')
    # Ollama native
    try:
        r = requests.get(f"{base}/api/tags", timeout=3)
        if r.status_code == 200:
            return [m['name'] for m in r.json().get('models', [])]
    except Exception:
        pass
    # OpenAI-compatible (LM Studio, llama.cpp server, etc.)
    try:
        r = requests.get(f"{base}/v1/models", timeout=3)
        if r.status_code == 200:
            return [m['id'] for m in r.json().get('data', [])]
    except Exception:
        pass
    return []


def _discover_remote_models(base_url: str, api_key: str) -> tuple[list[str], str]:
    """
    Query an OpenAI-compatible remote service's /models endpoint.
    Returns (model_id_list, error_message). On success error_message is ''.
    """
    base = base_url.rstrip('/')
    try:
        hdrs = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        r = requests.get(f"{base}/models", headers=hdrs, timeout=8)
        if r.status_code == 200:
            data = r.json().get('data', [])
            ids  = sorted(m['id'] for m in data if 'id' in m)
            if ids:
                return ids, ''
            return [], "No models returned by the service."
        return [], f"HTTP {r.status_code}: {r.text[:200]}"
    except requests.exceptions.ConnectionError:
        return [], f"Could not connect to {base_url} — check the URL and that the service is reachable."
    except requests.exceptions.Timeout:
        return [], "Request timed out — service may be slow or unreachable."
    except Exception as e:
        return [], f"Unexpected error: {e}"


SYSTEM_PROMPT = """You are a Bloomberg-style financial AI assistant integrated with the Strategy Analyzer Terminal.

You have access to live market data tools that can fetch:
- Stock prices, fundamentals, and valuation metrics
- Historical price data and volatility
- Sector performance
- Macro indicators (GDP, CPI, rates, etc.) from FRED & World Bank
- Options data and implied volatility
- Stock screener results
- Latest news headlines (NewsAPI, GDELT, RSS Feeds, Finnhub — multi-source fallback)
- Cryptocurrency data (CoinGecko + yfinance)

Guidelines:
- Always call the relevant data tool before answering financial data questions
- For ANY question about news, recent events, what's happening with a stock or in markets:
  call get_news FIRST — it tries multiple sources in configured priority order.
  Do NOT rely on your training knowledge for current events.
- For crypto questions, use get_crypto_data (CoinGecko primary, yfinance fallback)
- Be concise and precise — like a Bloomberg terminal, not a textbook
- Format numbers clearly: prices to 2-4 dp, % to 2 dp, large numbers as $XB/$XM
- When you fetch data, summarise the key insights, don't just list raw numbers
- If the user asks about a company by name, use search_ticker first to get the symbol
- For comparisons, always call compare_stocks so you have accurate returns/vol data
- Suggest relevant terminal commands the user can run for deeper visual analysis
- Be direct — lead with the answer, then provide context
"""


# ── Compact system prompt for small/no-tool-call models ───────────────────────
# Tells the model its only job is to narrate the pre-fetched data block.
SYSTEM_PROMPT_NO_TOOLS = """You are a concise Bloomberg-style financial assistant.
Live market data will be provided to you inside a [LIVE DATA] block.
Your job:
1. Read the data in [LIVE DATA] carefully.
2. Summarise the key numbers and insights in 3-6 sentences.
3. Format prices to 2 dp, percentages to 2 dp, large caps as $XB/$XM.
4. Lead with the most important figure, then add context.
5. If no [LIVE DATA] block is present, answer from general knowledge and be honest about limitations.
Do NOT invent numbers. Do NOT repeat every field — highlight what matters."""


# ── Common words that look like tickers but aren't ─────────────────────────────
_NOT_TICKERS = {
    'A','I','AT','BE','BY','DO','GO','IF','IN','IS','IT','MY','NO','OF','ON',
    'OR','SO','TO','UP','US','WE','ME','AN','AS','HE','HI','AM','ARE','FOR',
    'THE','AND','BUT','NOT','YOU','ALL','CAN','HAS','HAD','ITS','WHO','HOW',
    'NOW','NEW','OUT','GET','USE','HER','TWO','WAY','MAY','SAY','EACH','FROM',
    'BEEN','HAVE','THAT','THIS','THEY','WILL','WITH','WHAT','WHEN','WERE','YOUR',
    'SAID','THAN','THEN','THEM','WELL','ALSO','INTO','OVER','BACK','SOME','MORE',
    'BASE','BEST','NEXT','HIGH','LOW','BIG','OLD','FEW','OWN','LONG','LAST',
    'GOOD','GIVE','JUST','MAKE','SHOW','TELL','KNOW','TAKE','COME','LOOK','WANT',
    'NEED','SAME','MOST','YEAR','WEEK','DAYS','RATE','FREE','REAL','LIVE','OPEN',
    'PLAN','TEST','RISK','DATA','INFO','HELP','CHAT','TERM','COMP',
}

import re as _re

def _extract_tickers(text: str) -> list[str]:
    """Extract plausible stock ticker symbols from free text."""
    raw = _re.findall(r'\b([A-Z]{1,5})\b', text.upper())
    seen, out = set(), []
    for t in raw:
        if t not in _NOT_TICKERS and t not in seen:
            seen.add(t)
            out.append(t)
    return out[:6]  # cap at 6


def _detect_and_prefetch(user_message: str) -> tuple[str, list]:
    """
    Rule-based intent detector for small models that cannot call tools themselves.

    Analyses the user's message, decides which Strategy Terminal tool(s) to run,
    executes them, and returns:
      - context_block : str  — formatted data block to inject into the LLM prompt
      - tool_calls_made: list — same format as the agentic-loop tool log

    Priority order:  Terminal data → internet APIs
    The LLM only needs to *narrate* what is here, not decide what to look up.
    """
    msg_up  = user_message.upper()
    msg_low = user_message.lower()
    tickers = _extract_tickers(user_message)

    results       = []   # list of (tool_name, args_dict, result_dict)
    calls_made    = []

    # ── 0. News (highest priority — query NewsAPI before anything else) ────────
    NEWS_TRIGGER_KW = (
        'news', 'headline', 'headlines', 'latest', 'today', 'happening',
        'announced', 'announcement', 'report', 'reported', 'released',
        'breaking', 'update', 'recent', 'recently', 'this week', 'yesterday',
        'article', 'story', 'coverage', 'press', 'what happened',
    )
    NEWS_TOPIC_MAP = {
        # topic keywords → NewsAPI query / category
        'federal reserve': ('Federal Reserve interest rate', 'business'),
        'fed ':           ('Federal Reserve FOMC', 'business'),
        'fomc':           ('Federal Reserve FOMC', 'business'),
        'inflation':      ('inflation CPI consumer price', 'business'),
        'cpi':            ('CPI inflation', 'business'),
        'earnings':       ('earnings quarterly results', 'business'),
        'crypto':         ('bitcoin ethereum cryptocurrency', ''),
        'bitcoin':        ('bitcoin cryptocurrency', ''),
        'oil':            ('oil OPEC crude price', 'business'),
        'gold':           ('gold price market', 'business'),
        'tech':           ('technology stocks', 'technology'),
        'ai ':            ('artificial intelligence AI stocks', 'technology'),
        'economy':        ('economy economic growth', 'business'),
        'market':         ('stock market Wall Street', 'business'),
        'geopolit':       ('geopolitics trade war sanctions', 'general'),
        'china':          ('China trade economy', 'general'),
        'ukraine':        ('Ukraine war economy', 'general'),
    }
    if any(kw in msg_low for kw in NEWS_TRIGGER_KW):
        # Determine query — ticker-specific or topic-based
        if tickers:
            # Get ticker + company name for a richer search
            tkr = tickers[0]
            try:
                import yfinance as _yf2
                _info2 = _yf2.Ticker(tkr).info
                _name2 = _info2.get('shortName') or _info2.get('longName') or ''
            except Exception:
                _name2 = ''
            na_q = f'{tkr} {_name2}'.strip()
            na_cat = ''
        else:
            # Topic-based search
            na_q, na_cat = '', 'business'
            for topic_kw, (q, cat) in NEWS_TOPIC_MAP.items():
                if topic_kw in msg_low:
                    na_q, na_cat = q, cat
                    break
        args = {'query': na_q, 'category': na_cat}
        r = tool_get_news(**args)
        if 'error' not in r and r.get('articles'):
            results.append(('get_news', args, r))
            calls_made.append({'name': 'get_news', 'args': args})

    # ── 1. Sector performance ──────────────────────────────────────────────────
    if any(w in msg_low for w in ('sector', 'sectors', 'sector rotation',
                                   'which sector', 'best sector', 'worst sector')):
        r = tool_get_sector_performance()
        results.append(('get_sector_performance', {}, r))
        calls_made.append({'name': 'get_sector_performance', 'args': {}})

    # ── 2. Macro indicators ────────────────────────────────────────────────────
    MACRO_KW = {
        'GDP': ['gdp','gross domestic'],
        'CPI': ['cpi','inflation','consumer price'],
        'UNRATE': ['unemployment','jobless','unrate'],
        'FEDFUNDS': ['fed funds','federal funds','fed rate','interest rate','fomc'],
        'DGS10': ['10 year','10yr','ten year','treasury yield','bond yield'],
        'DGS2':  ['2 year','2yr','two year'],
        'M2':    [' m2 ','money supply'],
        'RETAIL':['retail sales','retail'],
        'INDPRO':['industrial production','indpro'],
    }
    for indicator, keywords in MACRO_KW.items():
        if any(kw in msg_low for kw in keywords):
            r = tool_get_macro_data(indicator)
            results.append(('get_macro_data', {'indicator': indicator}, r))
            calls_made.append({'name': 'get_macro_data', 'args': {'indicator': indicator}})
            break   # one macro indicator per query is enough

    # ── 3. Stock screener ──────────────────────────────────────────────────────
    if any(w in msg_low for w in ('screen', 'screener', 'stock ideas',
                                   'find stocks', 'low beta', 'value stocks',
                                   'dividend stocks', 'cheap stocks')):
        # Parse beta hints from message
        min_beta, max_beta = 0.0, 3.0
        max_pe = 50.0
        if 'low beta' in msg_low:  max_beta = 0.8
        if 'high beta' in msg_low: min_beta = 1.5
        if 'value' in msg_low:     max_pe   = 20.0
        args = {'min_mktcap_b': 10.0, 'max_pe': max_pe,
                'min_beta': min_beta, 'max_beta': max_beta}
        r = tool_screen_stocks(**args)
        results.append(('screen_stocks', args, r))
        calls_made.append({'name': 'screen_stocks', 'args': args})

    # ── 4. Stock comparison ────────────────────────────────────────────────────
    compare_kw = ('compare', ' vs ', ' versus ', ' vs.', 'comparison',
                  'better stock', 'which is better', 'head to head')
    if len(tickers) >= 2 and any(kw in msg_low for kw in compare_kw):
        period = '1y'
        for p in ('1mo','3mo','6mo','1y','2y','5y'):
            if p in msg_low:
                period = p; break
        args = {'tickers': tickers[:4], 'period': period}
        r = tool_compare_stocks(**args)
        results.append(('compare_stocks', args, r))
        calls_made.append({'name': 'compare_stocks', 'args': args})

    # ── 5. Options / IV ───────────────────────────────────────────────────────
    elif tickers and any(w in msg_low for w in ('option', 'options', 'iv ', 'implied vol',
                                                  'puts', 'calls', 'expiry', 'strike')):
        args = {'ticker': tickers[0]}
        r = tool_get_options_summary(**args)
        results.append(('get_options_summary', args, r))
        calls_made.append({'name': 'get_options_summary', 'args': args})

    # ── 6. Price history ──────────────────────────────────────────────────────
    elif tickers and any(w in msg_low for w in ('history', 'historical', 'performance',
                                                  'return', 'returns', 'chart', 'trend',
                                                  'how has', 'how did', 'ytd', 'year to date',
                                                  '1mo','3mo','6mo','1y','2y','5y')):
        period = '1y'
        for p in ('1mo','3mo','6mo','1y','2y','5y'):
            if p in msg_low:
                period = p; break
        if 'ytd' in msg_low or 'year to date' in msg_low:
            period = '1y'
        for tkr in tickers[:2]:
            args = {'ticker': tkr, 'period': period}
            r = tool_get_price_history(**args)
            results.append(('get_price_history', args, r))
            calls_made.append({'name': 'get_price_history', 'args': args})

    # ── 7. Stock overview (default for any ticker mention) ────────────────────
    elif tickers:
        for tkr in tickers[:2]:
            args = {'ticker': tkr}
            r = tool_get_stock_overview(**args)
            results.append(('get_stock_overview', args, r))
            calls_made.append({'name': 'get_stock_overview', 'args': args})

    # ── 8. Crypto queries ─────────────────────────────────────────────────────
    CRYPTO_KW = ('bitcoin', 'btc', 'ethereum', 'eth', 'solana', 'sol', 'crypto',
                 'cryptocurrency', 'dogecoin', 'doge', 'xrp', 'ripple', 'cardano',
                 'ada', 'polkadot', 'dot', 'avalanche', 'avax', 'chainlink', 'link',
                 'coingecko', 'coin gecko')
    if any(kw in msg_low for kw in CRYPTO_KW):
        # Determine which coin
        coin_q = 'bitcoin'
        for kw in CRYPTO_KW:
            if kw in msg_low and kw not in ('crypto', 'cryptocurrency', 'coingecko', 'coin gecko'):
                coin_q = kw
                break
        args = {'query': coin_q}
        r = tool_get_crypto_data(**args)
        if 'error' not in r:
            results.append(('get_crypto_data', args, r))
            calls_made.append({'name': 'get_crypto_data', 'args': args})

    # ── 9. Ticker search (company name, no recognisable ticker) ───────────────
    if not tickers and not results:
        search_kw = ('who is', 'what is', 'ticker for', 'symbol for', 'find', 'search')
        if any(kw in msg_low for kw in search_kw):
            # Strip stop words and search the remainder
            query = _re.sub(r'\b(who|what|is|the|ticker|symbol|for|find|search)\b',
                            '', msg_low, flags=_re.I).strip()
            if query:
                args = {'query': query}
                r = tool_search_ticker(**args)
                results.append(('search_ticker', args, r))
                calls_made.append({'name': 'search_ticker', 'args': args})

    if not results:
        return '', []

    # ── Format results into a compact context block ────────────────────────────
    lines = ['[LIVE DATA — fetched from Strategy Terminal]']
    for tool_name, args, data in results:
        lines.append(f'\n--- {tool_name}({", ".join(f"{k}={v}" for k,v in args.items())}) ---')
        if 'error' in data:
            lines.append(f'ERROR: {data["error"]}')
            continue
        # Remove internal metadata keys
        clean = {k: v for k, v in data.items() if not k.startswith('_')}
        lines.append(json.dumps(clean, default=str, indent=2))
    lines.append('\n[END LIVE DATA]')

    return '\n'.join(lines), calls_made


def _call_llm(messages: list, provider: str,
              model_id: str, or_key: str, local_url: str,
              use_tools: bool = True) -> dict:
    """
    Unified LLM caller. Routes to local OpenAI-compatible endpoint or OpenAI.
    Both use the same OpenAI chat/completions schema.
    """
    payload: dict = {
        "model":       model_id,
        "messages":    messages,
        "temperature": 0.3,
        "max_tokens":  2048,
    }
    if use_tools:
        payload["tools"]       = TOOLS
        payload["tool_choice"] = "auto"

    if provider == "local":
        base = local_url.rstrip('/')
        url  = f"{base}/v1/chat/completions"
        hdrs = {"Content-Type": "application/json"}
        src = "Local LLM"
    elif provider == "openrouter":
        remote_url = local_url.rstrip('/')
        url  = f"{remote_url}/chat/completions"
        hdrs = {
            "Authorization": f"Bearer {or_key}",
            "Content-Type":  "application/json",
            "HTTP-Referer": "https://strategymind.ai",
            "X-Title": "StrategyTerminal",
        }
        src = "OpenRouter"
    else:
        remote_url = local_url.rstrip('/')
        url  = f"{remote_url}/chat/completions"
        hdrs = {
            "Authorization": f"Bearer {or_key}",
            "Content-Type":  "application/json",
        }
        src = "OpenAI"

    resp = requests.post(url, headers=hdrs, json=payload, timeout=120)
    if resp.status_code != 200:
        raise RuntimeError(f"{src} error {resp.status_code}: {resp.text[:400]}")
    return resp.json()


def _run_agentic_loop(user_message: str, history: list,
                      provider: str, model_id: str,
                      or_key: str, local_url: str,
                      has_tools: bool, user_id: int = None) -> tuple[str, list, list]:
    """
    Agentic tool-calling loop. Works for both local and OpenAI providers.
    Returns (final_text, tool_calls_made, context_docs).
    """
    import rag as _rag
    
    context_docs = []
    if user_id:
        context_docs = _rag.search_knowledge(user_message, top_k=3)
    
    context_block = ""
    if context_docs:
        context_block = "\n[KNOWLEDGE BASE]\n"
        for doc in context_docs:
            context_block += f"--- {doc['title']} ---\n{doc['chunk_text']}\n\n"
        context_block += "[END KNOWLEDGE BASE]\n"
    
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for msg in history[-10:]:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_message})

    if context_block:
        messages[-1]["content"] = f"{context_block}\n\n{messages[-1]['content']}"
    
    tool_calls_made: list = []
    MAX_ROUNDS = 4

    if not has_tools:
        # ── Pre-execution layer for small / no-tool-call models ────────────────
        # Detect intent from the user's message, run the matching Strategy
        # Terminal tools ourselves, and inject the live data as context so the
        # model only has to narrate — not figure out what to look up.
        context_block, tool_calls_made = _detect_and_prefetch(user_message)

        if context_block:
            # Swap to the compact summarisation prompt
            messages[0]["content"] = SYSTEM_PROMPT_NO_TOOLS
            # Append data block to the user turn
            messages[-1]["content"] = (
                f"{user_message}\n\n{context_block}\n\n"
                "Using only the [LIVE DATA] above, give a concise, accurate summary."
            )
        # else: no data found — fall through with original prompt + message
        # (model answers from general knowledge, fine for non-data questions)

        data   = _call_llm(messages, provider, model_id, or_key, local_url, use_tools=False)
        choice = data["choices"][0]
        return choice["message"].get("content", ""), tool_calls_made, context_docs

    for _ in range(MAX_ROUNDS):
        data    = _call_llm(messages, provider, model_id, or_key, local_url, use_tools=True)
        choice  = data["choices"][0]
        message = choice["message"]
        reason  = choice.get("finish_reason", "")

        if reason == "stop" or not message.get("tool_calls"):
            return message.get("content", ""), tool_calls_made, context_docs

        messages.append(message)
        for tc in message["tool_calls"]:
            fn_name = tc["function"]["name"]
            try:
                fn_args = json.loads(tc["function"]["arguments"])
            except Exception:
                fn_args = {}
            tool_calls_made.append({"name": fn_name, "args": fn_args})
            fn = TOOL_FN_MAP.get(fn_name)
            if fn:
                try:
                    result = fn(**fn_args)
                except Exception as e:
                    result = {"error": str(e)}
            else:
                result = {"error": f"Unknown tool: {fn_name}"}
            messages.append({
                "role":         "tool",
                "tool_call_id": tc["id"],
                "content":      json.dumps(result, default=str),
            })

    # Final pass without tools
    data   = _call_llm(messages, provider, model_id, or_key, local_url, use_tools=False)
    choice = data["choices"][0]
    return choice["message"].get("content", ""), tool_calls_made, context_docs


# ══════════════════════════════════════════════════════════════════════════════
# MINI CHARTS — rendered inline in chat responses
# ══════════════════════════════════════════════════════════════════════════════

def _spark_chart(ticker: str, period: str = "3mo"):
    """Small price sparkline rendered in chat."""
    try:
        import yfinance as yf
        df = yf.Ticker(ticker).history(period=period, interval='1d', auto_adjust=True)
        if df.empty:
            return
        color = T['green'] if df['Close'].iloc[-1] >= df['Close'].iloc[0] else T['red']
        fig = go.Figure(go.Scatter(
            x=df.index, y=df['Close'],
            fill='tozeroy',
            fillcolor=f"rgba({'0,200,83' if color == T['green'] else '255,23,68'},0.08)",
            line=dict(color=color, width=1.8),
        ))
        fig.update_layout(
            height=160, margin=dict(l=0, r=0, t=0, b=0),
            paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
            xaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
            yaxis=dict(showgrid=False, showticklabels=True,
                       zeroline=False, tickfont=dict(color=T['muted'], size=9)),
            showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    except Exception:
        pass


def _comparison_bar(comparison_data: list):
    """Horizontal bar chart for stock comparison."""
    if not comparison_data:
        return
    try:
        labels = [d["ticker"] for d in comparison_data]
        values = [d["total_return_pct"] for d in comparison_data]
        colors = [T['green'] if v >= 0 else T['red'] for v in values]
        fig = go.Figure(go.Bar(
            x=values, y=labels, orientation='h',
            marker_color=colors,
            text=[f"{v:+.1f}%" for v in values],
            textposition='outside',
            textfont=dict(color=T['white'], family='monospace', size=11),
        ))
        fig.update_layout(
            height=max(120, len(labels) * 40 + 40),
            margin=dict(l=10, r=60, t=10, b=10),
            paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
            xaxis=dict(gridcolor=T['border'], ticksuffix='%',
                       tickfont=dict(color=T['muted'], size=9)),
            yaxis=dict(tickfont=dict(color=T['amber'], family='monospace', size=11)),
            showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    except Exception:
        pass


def _sector_bar(sectors: list):
    """Sector performance bar chart."""
    if not sectors:
        return
    try:
        labels = [s["sector"] for s in sectors]
        values = [s["day_chg_pct"] for s in sectors]
        colors = [T['green'] if v >= 0 else T['red'] for v in values]
        fig = go.Figure(go.Bar(
            x=values, y=labels, orientation='h',
            marker_color=colors,
            text=[f"{v:+.2f}%" for v in values],
            textposition='outside',
            textfont=dict(color=T['white'], family='monospace', size=10),
        ))
        fig.update_layout(
            height=340, margin=dict(l=10, r=60, t=10, b=10),
            paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
            xaxis=dict(gridcolor=T['border'], ticksuffix='%',
                       tickfont=dict(color=T['muted'], size=9)),
            yaxis=dict(tickfont=dict(color=T['white'], family='monospace', size=10)),
            showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
# CHAT PAGE
# ══════════════════════════════════════════════════════════════════════════════

def chat_page():
    ss = st.session_state

    # ── Inline CSS ─────────────────────────────────────────────────────────────
    st.markdown("""
<style>
.chat-header {
    background: linear-gradient(90deg, #0f1729 0%, #1565c0 100%);
    padding: 10px 18px; border-radius: 8px; margin-bottom: 12px;
    font-family: monospace; color: #ffb300; font-size: 16px;
    font-weight: bold; letter-spacing: 2px;
}
.tool-pill {
    display: inline-block;
    background: #1e2d4a; color: #ffb300;
    font-family: monospace; font-size: 10px;
    padding: 2px 8px; border-radius: 12px;
    border: 1px solid #ffb300; margin: 2px 3px 2px 0;
}
.terminal-btn-hint {
    background: #0f1729; border: 1px solid #1565c0;
    border-radius: 6px; padding: 6px 12px;
    font-family: monospace; font-size: 11px; color: #546e7a;
    margin-top: 6px;
}
</style>
""", unsafe_allow_html=True)

    # ── Header ─────────────────────────────────────────────────────────────────
    st.markdown(
        "<div class='chat-header'>"
        "🤖 &nbsp; AI FINANCIAL ASSISTANT &nbsp;|&nbsp; "
        "<span style='color:#e8eaf6;font-size:12px'>Local LLM · OpenAI × Strategy Terminal</span>"
        "</div>",
        unsafe_allow_html=True)

    # ── Session state init ─────────────────────────────────────────────────────
    ss.setdefault('chat_history', [])
    ss.setdefault('chat_tool_log', [])
    ss.setdefault('chat_spark_tickers', [])
    ss.setdefault('chat_provider', 'local')          # ← local LLM is the default
    ss.setdefault('chat_local_url', DEFAULT_LOCAL_URL)
    ss.setdefault('chat_local_model', '')
    ss.setdefault('chat_local_models', [])           # discovered model list
    ss.setdefault('chat_model', OR_LABELS[0])        # OpenAI model choice
    ss.setdefault('chat_remote_models', [])          # discovered remote model list
    ss.setdefault('chat_or_available', [])          # OpenRouter available models

    # Always sync remote URL/model from persisted API keys so changes saved
    # in Terminal → API Keys are immediately reflected when opening AI Chat.
    saved_url   = ss.term_api_keys.get('openai_url',   '').strip()
    saved_model = ss.term_api_keys.get('openai_model', '').strip()
    ss.chat_remote_url   = saved_url or DEFAULT_REMOTE_URL
    ss.chat_remote_model = saved_model
    # Pre-seed the dropdown with the saved model so it's visible before Detect runs
    if saved_model and saved_model not in ss.chat_remote_models:
        ss.chat_remote_models = [saved_model] + [m for m in ss.chat_remote_models if m != saved_model]

    # ── Sidebar ────────────────────────────────────────────────────────────────
    with st.sidebar:
        st.markdown("---\n**🤖 AI Chat Settings**")

        provider = st.radio(
            "Provider",
            options=["🖥️ Local LLM", "☁️ Remote LLM", "☁️ OpenRouter (Free)"],
            index=0 if ss.chat_provider == 'local' else (2 if ss.chat_provider == 'openrouter' else 1),
            key="chat_provider_radio",
            horizontal=True,
        )
        if provider.startswith("🖥️"):
            ss.chat_provider = 'local'
        elif provider.startswith("☁️ OpenRouter"):
            ss.chat_provider = 'openrouter'
        else:
            ss.chat_provider = 'openai'

        # ── LOCAL LLM controls ─────────────────────────────────────────────────
        if ss.chat_provider == 'local':
            local_url = st.text_input(
                "Server URL",
                value=ss.chat_local_url,
                key="chat_local_url_input",
                placeholder="http://localhost:11434",
                help="Ollama: port 11434 · LM Studio: port 1234 · llama.cpp: port 8080",
            )
            ss.chat_local_url = local_url.strip().rstrip('/')

            col_refresh, col_status = st.columns([1, 2])
            if col_refresh.button("🔄 Detect", key="chat_detect_btn",
                                  use_container_width=True):
                with st.spinner("Scanning…"):
                    found = _discover_local_models(ss.chat_local_url)
                ss.chat_local_models = found
                if found and ss.chat_local_model not in found:
                    ss.chat_local_model = found[0]
                st.rerun()

            local_models = ss.chat_local_models
            if local_models:
                col_status.caption(f"✅ {len(local_models)} model(s) found")
                sel = st.selectbox(
                    "Model",
                    options=local_models,
                    index=local_models.index(ss.chat_local_model)
                          if ss.chat_local_model in local_models else 0,
                    key="chat_local_model_sel",
                )
                ss.chat_local_model = sel
                ht = _local_model_has_tools(sel)
                st.caption(
                    f"`{sel}`  "
                    f"{'✅ Tool calling likely supported' if ht else '⚠️ Tool calling may not work — knowledge only'}"
                )
            else:
                col_status.caption("⚠️ No models — click Detect")
                st.caption(
                    "Make sure your local LLM server is running:  \n"
                    "**Ollama:** `ollama serve`  \n"
                    "**LM Studio:** enable Local Server  \n"
                    "**llama.cpp:** `./server -m model.gguf`"
                )

            # Resolve active settings
            or_key    = ss.term_api_keys.get('openai_key', '').strip()
            model_id  = ss.chat_local_model
            has_tools = _local_model_has_tools(model_id) if model_id else False
            ready     = bool(model_id)

        # ── OPENROUTER (FREE) ─────────────────────────────────────────────
        elif ss.chat_provider == 'openrouter':
            ss.chat_remote_url = 'https://openrouter.ai/api/v1'
            OPENROUTER_KEY = os.environ.get('OPENROUTER_API_KEY', '').strip()
            or_key = OPENROUTER_KEY
            st.caption("✅ Using free OpenRouter API")

            st.markdown("**Select Model:**")
            or_models = [
                # Top Free Models (from OpenRouter free collection)
                "minimax/minimax-m2.5:free",
                "tencent/hy3-preview:free",
                "nvidia/nemotron-3-super-120b-a12b:free",
                "inclusionai/ling-2.6-1t:free",
                "openrouter/owl-alpha",
                "poolside/laguna-m.1:free",
                "openai/gpt-oss-120b:free",
                "z-ai/glm-4.5-air:free",
                # NVIDIA Series
                "nvidia/nemotron-3-nano-30b-a3b:free",
                "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
                "nvidia/nemotron-nano-9b-v2:free",
                "nvidia/nemotron-nano-12b-v2-vl:free",
                # Google Series
                "google/gemma-4-31b-it:free",
                "google/gemma-4-26b-a4b-it:free",
                "google/gemini-2.0-flash-exp",
                "google/gemma-2-9b-it",
                # OpenAI & Anthropic
                "openai/gpt-oss-20b:free",
                "anthropic/claude-3-haiku",
                # Meta & Mistral
                "meta-llama/llama-3.1-8b-instruct",
                "mistralai/mistral-7b-instruct",
                # Chinese Models
                "deepseek/deepseek-chat",
                "deepseek/deepseek-coder-v2",
                "qwen/qwen2.5-7b-instruct",
                "qwen/qwen2.5-coder-7b-instruct",
                "01-ai/yi-1.5-6b-chat",
                # Microsoft & Others
                "microsoft/phi-4-mini",
                "poolside/laguna-xs.2:free",
                "NousResearch/Nous-Hermes-2-Mistral-7B-DPO",
                "Cognitivecomputations/dolphin-2.9.1-mistral-7b",
            ]

            col_detect_or, col_status_or = st.columns([1, 2])
            if col_detect_or.button("🔄 Detect", key="chat_or_detect_btn", use_container_width=True):
                with st.spinner("Testing all free models (this may take ~1-2 min)..."):
                    working_models = []
                    errors = []
                    for model in or_models:
                        try:
                            test_url = "https://openrouter.ai/api/v1/chat/completions"
                            test_payload = {
                                "model": model,
                                "messages": [{"role": "user", "content": "Hi"}],
                                "max_tokens": 5,
                            }
                            test_hdrs = {
                                "Authorization": f"Bearer {OPENROUTER_KEY}",
                                "Content-Type": "application/json",
                                "HTTP-Referer": "https://strategymind.ai",
                                "X-Title": "StrategyTerminal",
                            }
                            r = requests.post(test_url, headers=test_hdrs, json=test_payload, timeout=25)
                            if r.status_code == 200:
                                working_models.append(model)
                            else:
                                errors.append(f"{model.split('/')[-1]}: {r.status_code}")
                        except Exception as e:
                            errors.append(f"{model.split('/')[-1]}: {str(e)[:25]}")

                    if working_models:
                        ss.chat_or_available = working_models
                        st.session_state.chat_or_detected = True
                    else:
                        ss.chat_or_available = []
                    ss.chat_or_errors = errors
                    st.rerun()

            if hasattr(ss, 'chat_or_available') and ss.chat_or_available:
                col_status_or.caption(f"✅ {len(ss.chat_or_available)} model(s) working: {', '.join([m.split('/')[-1] for m in ss.chat_or_available])}")
            elif hasattr(ss, 'chat_or_errors') and ss.chat_or_errors:
                err_summary = '; '.join([e for e in ss.chat_or_errors[:8]])
                col_status_or.caption(f"⚠️ {err_summary}")

            available = ss.chat_or_available if hasattr(ss, 'chat_or_available') and ss.chat_or_available else or_models

            ss.setdefault('chat_or_model', available[0])
            model_id = st.selectbox(
                "Model",
                options=available,
                index=available.index(ss.chat_or_model) if ss.chat_or_model in available else 0,
                key="chat_or_model_sel",
                help=f"Select from {len(available)} available models",
            )
            ss.chat_or_model = model_id
            has_tools = False
            st.caption(f"`{model_id}`")
            ready = bool(model_id)

        # ── REMOTE LLM controls ────────────────────────────────────────────
        else:
            remote_url = st.text_input(
                "Remote API URL",
                value=ss.chat_remote_url,
                key="chat_remote_url_input",
                placeholder="http://your-remote-service/v1",
                help="Base URL of your OpenAI-compatible remote service (without /chat/completions)",
            )
            ss.chat_remote_url = remote_url.strip().rstrip('/')

            or_key = ss.term_api_keys.get('openai_key', '').strip()
            if or_key:
                st.caption("✅ API key loaded from Terminal → API Keys")
            else:
                st.caption("⚠️ No key — add in **Terminal → 🔑 API Keys → OpenAI**")

            col_detect, col_status = st.columns([1, 2])
            if col_detect.button("🔄 Detect", key="chat_remote_detect_btn",
                                 use_container_width=True):
                if not ss.chat_remote_url:
                    st.warning("Enter a Remote API URL first.")
                else:
                    with st.spinner("Querying remote service…"):
                        found, err = _discover_remote_models(ss.chat_remote_url, or_key)
                    if found:
                        ss.chat_remote_models = found
                        if ss.chat_remote_model not in found:
                            ss.chat_remote_model = found[0]
                        st.rerun()
                    else:
                        ss.chat_remote_models = []
                        col_status.caption(f"⚠️ {err}")

            remote_models = ss.chat_remote_models
            if remote_models:
                col_status.caption(f"✅ {len(remote_models)} model(s) found")
                sel_remote = st.selectbox(
                    "Model",
                    options=remote_models,
                    index=remote_models.index(ss.chat_remote_model)
                          if ss.chat_remote_model in remote_models else 0,
                    key="chat_remote_model_sel",
                )
                ss.chat_remote_model = sel_remote
                model_id  = sel_remote
                has_tools = True
                st.caption(f"`{model_id}`")
            else:
                col_status.caption("⚠️ No models — click Detect")
                model_id  = ss.chat_remote_model
                has_tools = True

            ready = bool(or_key and model_id and ss.chat_remote_url)

        st.markdown("---")
        if st.button("🗑️ Clear Chat", key="chat_clear_btn"):
            ss.chat_history       = []
            ss.chat_tool_log      = []
            ss.chat_spark_tickers = []
            st.rerun()

        st.markdown("**💡 Example questions:**")
        for ex in [
            "What's the latest news on Apple?",
            "Any Fed or interest rate news today?",
            "What's Apple's P/E vs Microsoft?",
            "Which sectors are up today?",
            "Screen for low-beta value stocks",
            "What's Bitcoin price today?",
            "What's the implied vol on TSLA?",
            "How has NVDA performed vs SPY in 2024?",
            "What's the current Fed funds rate?",
        ]:
            if st.button(ex, key=f"ex_{ex[:20]}", use_container_width=True):
                ss['_chat_prefill'] = ex
                st.rerun()

    # ── Not-ready banners ──────────────────────────────────────────────────────
    if not ready:
        if ss.chat_provider == 'local':
            st.info(
                "**Local LLM not connected.**  \n"
                "1. Start your local server (Ollama / LM Studio / llama.cpp)  \n"
                "2. Enter the server URL in the sidebar  \n"
                "3. Click **🔄 Detect** to discover available models  \n\n"
                "Ollama default: `http://localhost:11434`  \n"
                "LM Studio default: `http://localhost:1234`"
            )
        elif ss.chat_provider == 'openrouter':
            st.success("☁️ **OpenRouter (Free)** ready to use!")
        else:
            st.info(
                "**Remote LLM not configured.**  \n"
                "In the sidebar:  \n"
                "1. Enter your remote service base URL  \n"
                "2. Add your API key in **Terminal → 🔑 API Keys → OpenAI**  \n"
                "3. Enter the model name your service expects"
            )
        st.markdown("The assistant can answer questions like:")
        for ex in [
            "📰 *\"What's the latest news on NVDA or the Fed?\"*",
            "📈 *\"What's NVDA's forward P/E and how does it compare to AMD?\"*",
            "🌍 *\"Which sectors are outperforming today?\"*",
            "📉 *\"Show me low-volatility dividend stocks\"*",
            "💹 *\"What's the current implied vol on TSLA options?\"*",
            "🏦 *\"What does the latest CPI print mean for rates?\"*",
        ]:
            st.markdown(ex)
        return

    # ── Render chat history ────────────────────────────────────────────────────
    for i, msg in enumerate(ss.chat_history):
        role = msg["role"]
        with st.chat_message(role, avatar="🤖" if role == "assistant" else "👤"):
            st.markdown(msg["content"])

            tool_log = next((t for t in ss.chat_tool_log if t["turn"] == i), None)
            if tool_log and tool_log["calls"]:
                pills = " ".join(
                    f"<span class='tool-pill'>⚡ {c['name']}"
                    f"({', '.join(str(v) for v in c['args'].values() if v)})</span>"
                    for c in tool_log["calls"]
                )
                st.markdown(pills, unsafe_allow_html=True)

            if tool_log and tool_log.get("terminal_cmds"):
                st.markdown(
                    "<div class='terminal-btn-hint'>Open in Terminal →</div>",
                    unsafe_allow_html=True)
                cols = st.columns(min(4, len(tool_log["terminal_cmds"])))
                for j, cmd in enumerate(tool_log["terminal_cmds"]):
                    if cmd and cols[j % len(cols)].button(
                            f"📟 {cmd}", key=f"tc_{i}_{j}_{cmd}",
                            use_container_width=True):
                        ss.term_cmd       = cmd
                        ss['_cmd_val']    = cmd
                        ss['_input_gen']  = ss.get('_input_gen', 0) + 1
                        ss['_should_run'] = True
                        ss.term_history.append(cmd)
                        ss.current_strategy = "TERMINAL"
                        st.rerun()

            if tool_log:
                for tc in tool_log["calls"]:
                    if tc["name"] in ("get_stock_overview", "get_price_history"):
                        tkr = tc["args"].get("ticker", "")
                        per = tc["args"].get("period", "3mo")
                        if tkr:
                            _spark_chart(tkr, per)
                    elif tc["name"] == "compare_stocks":
                        tickers = tc["args"].get("tickers", [])
                        per     = tc["args"].get("period", "1y")
                        if tickers:
                            result = tool_compare_stocks(tickers, per)
                            _comparison_bar(result.get("comparison", []))
                    elif tc["name"] == "get_sector_performance":
                        result = tool_get_sector_performance()
                        _sector_bar(result.get("sectors", []))

    # ── Chat input ─────────────────────────────────────────────────────────────
    prefill    = ss.pop('_chat_prefill', '')
    user_input = st.chat_input("Ask anything about markets, stocks, macro, options…",
                               key="chat_input")
    if prefill and not user_input:
        user_input = prefill
    if not user_input:
        return

    # ── Show user message ──────────────────────────────────────────────────────
    with st.chat_message("user", avatar="👤"):
        st.markdown(user_input)

    turn_idx = len(ss.chat_history) + 1

    # ── Call agentic loop (local or OpenAI) ────────────────────────────────
    provider_label = "🖥️ Local" if ss.chat_provider == 'local' else (f"☁️ OpenRouter" if ss.chat_provider == 'openrouter' else f"☁️ {ss.chat_model}")
    with st.chat_message("assistant", avatar="🤖"):
        with st.spinner(f"Thinking via {provider_label}…"):
            try:
                if ss.chat_provider == 'local':
                    active_url = ss.chat_local_url
                elif ss.chat_provider == 'openrouter':
                    active_url = 'https://openrouter.ai/api/v1'
                else:
                    active_url = ss.chat_remote_url
                response_text, tool_calls, context_docs = _run_agentic_loop(
                    user_input, ss.chat_history,
                    provider  = ss.chat_provider,
                    model_id  = model_id,
                    or_key    = or_key,
                    local_url = active_url,
                    has_tools = has_tools,
                    user_id  = st.session_state.get('user_id'),
                )
            except Exception as e:
                response_text = f"⚠️ Error: {e}"
                tool_calls    = []

        st.markdown(response_text)

        terminal_cmds = []
        for tc in tool_calls:
            fn = TERMINAL_SHORTCUTS.get(tc["name"])
            if fn:
                cmd = fn(tc["args"])
                if cmd and cmd not in terminal_cmds:
                    terminal_cmds.append(cmd.strip())

        if tool_calls:
            pills = " ".join(
                f"<span class='tool-pill'>⚡ {c['name']}"
                f"({', '.join(str(v) for v in c['args'].values() if v)})</span>"
                for c in tool_calls
            )
            st.markdown(pills, unsafe_allow_html=True)

        if terminal_cmds:
            st.markdown(
                "<div class='terminal-btn-hint'>Open in Terminal for full visual →</div>",
                unsafe_allow_html=True)
            cols = st.columns(min(4, len(terminal_cmds)))
            for j, cmd in enumerate(terminal_cmds):
                if cols[j % len(cols)].button(
                        f"📟 {cmd}", key=f"live_tc_{j}_{cmd}",
                        use_container_width=True):
                    ss.term_cmd       = cmd
                    ss['_cmd_val']    = cmd
                    ss['_input_gen']  = ss.get('_input_gen', 0) + 1
                    ss['_should_run'] = True
                    ss.term_history.append(cmd)
                    ss.current_strategy = "TERMINAL"
                    st.rerun()

        for tc in tool_calls:
            if tc["name"] in ("get_stock_overview", "get_price_history"):
                tkr = tc["args"].get("ticker", "")
                per = tc["args"].get("period", "3mo")
                if tkr:
                    _spark_chart(tkr, per)
            elif tc["name"] == "compare_stocks":
                tickers = tc["args"].get("tickers", [])
                per     = tc["args"].get("period", "1y")
                if tickers:
                    result = tool_compare_stocks(tickers, per)
                    _comparison_bar(result.get("comparison", []))
            elif tc["name"] == "get_sector_performance":
                result = tool_get_sector_performance()
                _sector_bar(result.get("sectors", []))

    # ── Save to history ────────────────────────────────────────────────────────
    user_id = st.session_state.get('user_id')
    if user_id:
        import rag as _rag
        _rag.add_chat_message(user_id, "user", user_input, context_docs if context_docs else None)
        _rag.add_chat_message(user_id, "assistant", response_text)
    
    ss.chat_history.append({"role": "user",      "content": user_input})
    ss.chat_history.append({"role": "assistant", "content": response_text})
    ss.chat_tool_log.append({
        "turn":          turn_idx,
        "calls":         tool_calls,
        "terminal_cmds": terminal_cmds,
    })
    if len(ss.chat_history) > 60:
        ss.chat_history  = ss.chat_history[-60:]
        ss.chat_tool_log = ss.chat_tool_log[-30:]