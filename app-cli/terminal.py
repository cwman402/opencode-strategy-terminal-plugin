"""
terminal.py –   -style terminal: colour palette, lookup tables,
              market data fetch helpers, command implementations, and the Terminal page.
"""
import re, json, time
from datetime import datetime, timedelta
try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
import requests

try:
    import yfinance as yf
    _YF_OK = True
except ImportError:
    _YF_OK = False

from config import CHART_STYLE
from database import (get_user_api_keys, save_user_api_keys,
                       add_price_alert, remove_price_alert, get_user_alerts)
from features import (cmd_wl, cmd_earn, cmd_ecal, cmd_pnl, cmd_corr, cmd_vol,
                       cmd_anr, cmd_rv, cmd_ipo, cmd_insider, cmd_short,
                       cmd_tra, cmd_risk, cmd_top, cmd_polygon_iv,
                       cmd_ind, cmd_wb, cmd_oas, cmd_oasd)
from terminal_pdf import generate_terminal_pdf

# ── Terminal colour palette (dark/amber    feel) ────────────────────────
T = {
    'bg':      '#0a0e1a',
    'panel':   '#0d1326',
    'border':  '#1e3a5f',
    'amber':   '#ffb300',
    'green':   '#00e676',
    'red':     '#ff1744',
    'blue':    '#40c4ff',
    'white':   '#e0e0e0',
    'muted':   '#607d8b',
    'header':  '#1a2a4a',
}

TERM_CSS = f"""
<style>
.term-panel {{
    background:{T['panel']}; border:1px solid {T['border']};
    border-radius:6px; padding:14px; margin-bottom:8px;
}}
.term-header {{
    background:{T['header']}; color:{T['amber']};
    font-family:monospace; font-size:13px; font-weight:700;
    padding:6px 12px; border-radius:4px 4px 0 0;
    letter-spacing:1px;
}}
.term-ticker {{
    display:inline-block; background:{T['header']}; color:{T['amber']};
    font-family:monospace; font-size:12px;
    padding:3px 8px; border-radius:3px; margin:2px;
}}
.term-up   {{ color:{T['green']}; font-family:monospace; font-weight:bold; }}
.term-dn   {{ color:{T['red']};   font-family:monospace; font-weight:bold; }}
.term-neu  {{ color:{T['white']}; font-family:monospace; }}
.term-lbl  {{ color:{T['muted']}; font-family:monospace; font-size:11px; }}
.term-val  {{ color:{T['amber']}; font-family:monospace; font-size:14px; font-weight:bold; }}
.term-cmd-hist {{ color:{T['blue']}; font-family:monospace; font-size:12px; }}
.fkey {{
    display:inline-block; background:#1a2744; color:{T['amber']};
    font-family:monospace; font-size:11px; padding:2px 6px;
    border:1px solid #2a3f6f; border-radius:3px; margin:1px;
}}
</style>
"""

# ── Lookup tables ──────────────────────────────────────────────────────────────
WORLD_INDICES = [
    ('S&P 500',     '^GSPC'),  ('NASDAQ',      '^IXIC'),  ('DOW',        '^DJI'),
    ('Russell 2000','^RUT'),   ('FTSE 100',    '^FTSE'),  ('DAX',        '^GDAXI'),
    ('CAC 40',      '^FCHI'),  ('Nikkei 225',  '^N225'),  ('Hang Seng',  '^HSI'),
    ('Shanghai',    '000001.SS'),('ASX 200',   '^AXJO'),  ('KOSPI',      '^KS11'),
    ('VIX',         '^VIX'),   ('MOVE Index',  '^MOVE'),
]

# Cash index symbol → (futures label, futures symbol). Used by WEI to show
# the matching overnight future, its change, and the implied cash open.
INDEX_FUTURES = {
    '^GSPC': ('ES',  'ES=F'),
    '^IXIC': ('NQ',  'NQ=F'),
    '^DJI':  ('YM',  'YM=F'),
    '^RUT':  ('RTY', 'RTY=F'),
}

FX_PAIRS = [
    ('EUR/USD','EURUSD=X'),('GBP/USD','GBPUSD=X'),('USD/JPY','JPY=X'),
    ('AUD/USD','AUDUSD=X'),('USD/CHF','CHF=X'),   ('USD/CAD','CAD=X'),
    ('NZD/USD','NZDUSD=X'),('USD/CNY','CNY=X'),   ('USD/HKD','HKD=X'),
    ('USD/SGD','SGD=X'),   ('USD/KRW','KRW=X'),   ('USD/MXN','MXN=X'),
]

CRYPTO_PAIRS = [
    ('Bitcoin',   'BTC-USD'),('Ethereum','ETH-USD'),('BNB',       'BNB-USD'),
    ('Solana',    'SOL-USD'),('XRP',     'XRP-USD'),('Cardano',   'ADA-USD'),
    ('Dogecoin',  'DOGE-USD'),('Avalanche','AVAX-USD'),('Chainlink','LINK-USD'),
    ('Polkadot',  'DOT-USD'),
]

YIELD_TICKERS = [
    ('1M','TB1MS','US1M=X'), ('3M','^IRX','US3M=X'),  ('6M','DTB6','US6M=X'),
    ('1Y','DGS1','US1Y=X'),  ('2Y','^TWOYEAR','US2Y=X'),('5Y','DGS5','US5Y=X'),
    ('7Y','DGS7','US7Y=X'),  ('10Y','^TNX','US10Y=X'), ('20Y','DGS20','US20Y=X'),
    ('30Y','^TYX','US30Y=X'),
]

FRED_SERIES = {
    'GDP':      ('GDP',        'US Real GDP (Quarterly, $B)'),
    'GDPGROWTH':('A191RL1Q225SBEA','US Real GDP Growth Rate (%)'),
    'CPI':      ('CPIAUCSL',   'US CPI (Urban, All Items)'),
    'INFLATION':('T10YIE',     'US 10Y Breakeven Inflation (%)'),
    'UNRATE':   ('UNRATE',     'US Unemployment Rate (%)'),
    'FEDFUNDS': ('FEDFUNDS',   'Federal Funds Effective Rate (%)'),
    'DGS10':    ('DGS10',      'US 10Y Treasury Yield (%)'),
    'DGS2':     ('DGS2',       'US 2Y Treasury Yield (%)'),
    'SPREAD':   ('T10Y2Y',     '10Y-2Y Yield Spread (bps)'),
    'M2':       ('M2SL',       'M2 Money Supply ($B)'),
    'INDPRO':   ('INDPRO',     'Industrial Production Index'),
    'RETAIL':   ('RSXFS',      'US Retail Sales (ex Auto, $M)'),
    'HOUSING':  ('HOUST',      'US Housing Starts (Thousands)'),
    'PMI':      ('MANEMP',     'Manufacturing Employment'),
    'OIL':      ('DCOILWTICO', 'WTI Crude Oil Price ($/bbl)'),
    'GOLD':     ('GOLDAMGBD228NLBM','Gold Price ($/oz)'),
    'VIX':      ('VIXCLS',     'CBOE VIX Index'),
    'DXY':      ('DTWEXBGS',   'USD Trade-Weighted Index'),
}

# ── CoinGecko coin name map (shared by COIN command and chat.py) ─────────────
COIN_MAP = {
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
    'binancecoin': 'binancecoin', 'bnb': 'binancecoin',
}

COMMAND_HELP = """
┌─────────────────────────────────────────────────────────────────────────────┐
│                    📟  TERMINAL COMMAND REFERENCE                           │
├──────────────────────┬──────────────────────────────────────────────────────┤
│  SECURITY COMMANDS   │                                                      │
│  AAPL                │  Overview (price, stats, financials)                 │
│  AAPL GP [period]    │  Price chart  (1d 5d 1mo 3mo 6mo 1y 2y 5y max)      │
│  AAPL DES            │  Company description & key info                      │
│  AAPL FA             │  Financials (income / balance / cash flow)           │
│  AAPL NEWS           │  Latest news headlines                               │
│  AAPL OPT            │  Options chain (nearest expiry)                      │
│  AAPL DVD            │  Dividend history                                    │
│  AAPL COMP peer1 …   │  Compare vs peers                                    │
├──────────────────────┼──────────────────────────────────────────────────────┤
│  MARKET COMMANDS     │                                                      │
│  WEI                 │  World equity indices dashboard                      │
│  MOVERS [g/l/a]      │  Market movers: gainers / losers / active            │
│  FX                  │  Forex monitor (major pairs)                         │
│  CRYPTO              │  Crypto dashboard                                    │
│  CRYPTO TOP          │  Top 10 cryptos by market cap (CoinGecko)             │
│  COIN bitcoin        │  Single-coin deep dive (price, ATH, supply, chart)    │
│  COIN ethereum       │  Ethereum deep dive via CoinGecko                     │
│  COIN solana         │  Solana deep dive                                     │
│  RATES               │  US yield curve & treasury rates                     │
│  CMDTY               │  Commodities (oil, gold, silver, nat gas…)           │
│  SECTOR              │  S&P 500 sector performance                          │
├──────────────────────┼──────────────────────────────────────────────────────┤
│  INDEX & FIXED INCOME│                                                      │
│  IND                 │  Index lookup — all major indices                    │
│  IND SPX             │  Index lookup — S&P 500 detail                       │
│  IND ^GSPC           │  Index lookup — by yahoo symbol                      │
│  WB                  │  World bond yields (10Y government)                  │
│  OAS                 │  Credit spread dashboard — IG/HY OAS (ICE BofA, bps) │
│  OAS IG              │  Focus: IG Corp OAS (credit risk gauge)              │
│  OAS HY              │  Focus: High Yield OAS                               │
│  OAS AAA … BBB       │  Focus: any rating — AAA, AA, A, BBB, BB, B          │
│  OASD                │  OAS duration by maturity bucket                     │
│  OASD IG             │  IG OAS across 1-3Y → 15+Y buckets                   │
│  OASD HY             │  High Yield OAS duration                             │
│  OASD 1-3Y           │  Short-end OAS history & detail                      │
│  OASD 10-15Y         │  Long-end OAS history & detail                       │
├──────────────────────┼──────────────────────────────────────────────────────┤
│  MACRO / ECON        │                                                      │
│  ECON                │  Macro dashboard (GDP, CPI, rates, jobs)             │
│  ECON GDP            │  Specific FRED series (see list above)               │
│  ECON GLOBAL         │  Global macro: GDP, inflation, unemployment by country│
│                      │  (World Bank — free, no key)                         │
│  FRED SERIES_ID      │  Any raw FRED series by ID                           │
├──────────────────────┼──────────────────────────────────────────────────────┤
│  SCREEN              │  Quick stock screener (via yfinance)                 │
│  SEARCH apple        │  Search by company name or partial ticker            │
│  SEARCH TSLA         │  Lookup ticker → full name, exchange, type           │
│  PORT                │  Live monitor of your loaded strategies              │
│  NEWS                │  Top business headlines  (via NewsAPI if key set)    │
│  NEWS TOP            │  Top global headlines across all categories          │
│  NEWS MACRO          │  Macro / economics & central bank news               │
│  NEWS TECH           │  Technology sector news                              │
│  NEWS CRYPTO         │  Cryptocurrency & digital assets news                │
│  NEWS EARNINGS       │  Earnings & corporate results headlines              │
│  NEWS <query>        │  Search any topic  e.g.  NEWS federal reserve        │
│  NEWS FEED           │  Aggregated news from 13+ RSS feeds (free)           │
│  NEWS SENTIMENT      │  News with GDELT tone/sentiment scoring              │
│  SENTIMENT AAPL      │  Sentiment analysis for a specific ticker            │
│  AAPL NEWS           │  Latest news headlines for a specific ticker         │
├──────────────────────┼──────────────────────────────────────────────────────┤
│  VOLATILITY / OPTIONS (requires Polygon.io key)                             │
│  IV AAPL             │  Full IV dashboard: term structure, IV vs RV,        │
│                      │  ATM option prices (BS), Greeks, IV skew             │
│  IV TSLA 1y          │  Custom lookback period                              │
├──────────────────────┼──────────────────────────────────────────────────────┤
│  WATCHLIST           │                                                      │
│  WL                  │  Watchlist dashboard (prices, 1M chart)              │
│  WL ADD AAPL [label] │  Add ticker to watchlist                             │
│  WL REMOVE AAPL      │  Remove ticker from watchlist                        │
├──────────────────────┼──────────────────────────────────────────────────────┤
│  EARNINGS / CALENDAR │                                                      │
│  EARN                │  Earnings calendar for watchlist                     │
│  EARN AAPL           │  Earnings detail + EPS surprise history              │
│  ECAL                │  Economic calendar (FOMC, CPI, NFP, GDP…)            │
├──────────────────────┼──────────────────────────────────────────────────────┤
│  P&L / POSITIONS     │                                                      │
│  PNL                 │  Portfolio P&L dashboard                             │
│  PNL ADD AAPL 100 150│  Add position (ticker, qty, cost basis)              │
│  PNL REMOVE AAPL     │  Remove position                                     │
├──────────────────────┼──────────────────────────────────────────────────────┤
│  CORRELATION         │                                                      │
│  CORR                │  Correlation matrix for watchlist (1Y)               │
│  CORR AAPL MSFT NVDA │  Custom tickers                                      │
│  CORR AAPL MSFT 6mo  │  Custom tickers + period                             │
├──────────────────────┼──────────────────────────────────────────────────────┤
│  VOLATILITY          │                                                      │
│  VOL                 │  VIX dashboard + sector ETF realised vol             │
│  VOL AAPL            │  Full vol: rolling RV, IV overlay, distribution,     │
│                      │  VaR, CVaR, skew/kurtosis, IV surface (if options)   │
│  VOL TSLA 6mo        │  Custom ticker + lookback period                     │
├──────────────────────┼──────────────────────────────────────────────────────┤
│  PDF EXPORT          │                                                      │
│  (button)            │  After any command, click ⬇️ Export as PDF          │
│                      │  to download the output as a formatted PDF report    │
├──────────────────────┼──────────────────────────────────────────────────────┤
│  ANALYST & ESTIMATES │                                                      │
│  ANR AAPL            │  Analyst ratings, price targets, consensus           │
│  RV AAPL             │  Relative value: peer valuation multiples table      │
│  RV AAPL MSFT GOOGL  │  Custom peer group                                   │
├──────────────────────┼──────────────────────────────────────────────────────┤
│  MARKET EVENTS       │                                                      │
│  IPO                 │  IPO calendar (upcoming + recent)                    │
│  TOP                 │  Today's top market news + sentiment                 │
│                      │  Tabs: ALL / EARNINGS / MACRO / IPO·M&A / CRYPTO     │
│  INSIDER AAPL        │  Insider buying/selling transactions                 │
│  SHORT AAPL          │  Short interest, days to cover, squeeze gauge        │
├──────────────────────┼──────────────────────────────────────────────────────┤
│  RETURN & RISK       │                                                      │
│  TRA AAPL            │  Total return vs SPY + QQQ (3Y default)              │
│  TRA AAPL SPY QQQ 5y │  Custom benchmarks + period                          │
│  RISK AAPL           │  Risk: beta, alpha, VaR, CVaR, scatter, rolling β    │
│  RISK TSLA QQQ       │  Risk vs custom benchmark                            │
├──────────────────────┼──────────────────────────────────────────────────────┤
│  PRICE ALERTS        │                                                      │
│  LIST ALERT          │  Show all your active price alerts                   │
│  NFLX ADD_ALERT EVERY 2%  │  Email alert every 2%, 4%, 6%… move in NFLX  │
│  NFLX REMOVE_ALERT   │  Remove all alerts on NFLX                           │
│  HELP                │  Show this help page                                 │
└──────────────────────┴──────────────────────────────────────────────────────┘

FRED series shortcuts: GDP GDPGROWTH CPI INFLATION UNRATE FEDFUNDS
                       DGS10 DGS2 SPREAD M2 INDPRO RETAIL HOUSING OIL GOLD VIX DXY
"""

# ── Autocomplete suggestion bank ──────────────────────────────────────────────
# Each entry: (command_string, description)
COMMAND_SUGGESTIONS = [
    # Security commands
    ("AAPL",                   "Apple – overview"),
    ("AAPL GP",                "Apple – price chart (default 1y)"),
    ("AAPL GP 1d",             "Apple – intraday chart"),
    ("AAPL GP 5d",             "Apple – 5-day chart"),
    ("AAPL GP 1mo",            "Apple – 1-month chart"),
    ("AAPL GP 3mo",            "Apple – 3-month chart"),
    ("AAPL GP 6mo",            "Apple – 6-month chart"),
    ("AAPL GP 1y",             "Apple – 1-year chart"),
    ("AAPL GP 5y",             "Apple – 5-year chart"),
    ("AAPL DES",               "Apple – company description"),
    ("AAPL FA",                "Apple – financials"),
    ("AAPL NEWS",              "Apple – news headlines"),
    ("AAPL OPT",               "Apple – options chain"),
    ("AAPL DVD",               "Apple – dividend history"),
    ("AAPL COMP MSFT GOOGL",   "Apple vs MSFT vs GOOGL"),
    ("TSLA",                   "Tesla – overview"),
    ("TSLA GP 1y",             "Tesla – 1-year chart"),
    ("TSLA OPT",               "Tesla – options chain"),
    ("MSFT",                   "Microsoft – overview"),
    ("NVDA",                   "Nvidia – overview"),
    ("GOOGL",                  "Alphabet – overview"),
    ("AMZN",                   "Amazon – overview"),
    ("META",                   "Meta – overview"),
    ("NFLX",                   "Netflix – overview"),
    ("JPM",                    "JPMorgan – overview"),
    ("SPY",                    "S&P 500 ETF – overview"),
    ("QQQ",                    "Nasdaq 100 ETF – overview"),
    ("IWM",                    "Russell 2000 ETF – overview"),
    # Market commands
    ("WEI",                    "World equity indices dashboard"),
    ("MOVERS",                 "Market movers (gainers/losers/active)"),
    ("MOVERS GAINERS",         "Top gainers today"),
    ("MOVERS LOSERS",          "Top losers today"),
    ("MOVERS ACTIVE",          "Most active today"),
    ("FX",                     "Forex – major pairs"),
    ("CRYPTO",                 "Crypto dashboard"),
    ("CRYPTO TOP",             "Top 10 cryptos by market cap (CoinGecko)"),
    ("COIN bitcoin",           "Bitcoin — deep dive (CoinGecko)"),
    ("COIN ethereum",          "Ethereum — deep dive"),
    ("COIN solana",            "Solana — deep dive"),
    ("RATES",                  "US yield curve & treasury rates"),
    ("CMDTY",                  "Commodities (oil, gold, silver, gas…)"),
    ("SECTOR",                 "S&P 500 sector performance"),
    ("NEWS",                   "Top business headlines (NewsAPI priority)"),
    ("NEWS TOP",               "Top global headlines — all categories"),
    ("NEWS MACRO",             "Macro / economics news — Fed, rates, GDP"),
    ("NEWS TECH",              "Technology sector headlines"),
    ("NEWS CRYPTO",            "Crypto & digital assets news"),
    ("NEWS EARNINGS",          "Earnings & corporate results news"),
    ("NEWS federal reserve",   "Search: federal reserve news"),
    ("NEWS inflation",         "Search: inflation news"),
    ("NEWS oil market",        "Search: oil market news"),
    ("NEWS FEED",              "Aggregated news from 13+ RSS feeds"),
    ("NEWS SENTIMENT",         "News with GDELT tone/sentiment scoring"),
    ("SENTIMENT AAPL",         "Sentiment analysis for AAPL"),
    ("SENTIMENT TSLA",         "Sentiment analysis for TSLA"),
    ("SENTIMENT NVDA",         "Sentiment analysis for NVDA"),
    ("ECON GLOBAL",            "Global macro comparison (World Bank)"),
    ("SCREEN",                 "Quick stock screener"),
    ("SEARCH apple",           "Search company by name"),
    ("SEARCH TSLA",            "Search by partial or full ticker"),
    ("PORT",                   "Live portfolio monitor"),
    # IV / Options (Polygon)
    ("IV AAPL",                "AAPL implied vol dashboard — term structure, option prices, Greeks"),
    ("IV TSLA",                "TSLA implied vol + ATM option pricing (1D/9D/1M/3M)"),
    ("IV SPY",                 "SPY implied vol vs realised vol + IV skew"),
    ("IV NVDA 1y",             "NVDA IV dashboard — 1-year lookback"),
    # Macro / ECON
    ("ECON",                   "Macro dashboard (GDP, CPI, rates, jobs)"),
    ("ECON GDP",               "FRED – GDP"),
    ("ECON CPI",               "FRED – CPI / inflation"),
    ("ECON UNRATE",            "FRED – unemployment rate"),
    ("ECON FEDFUNDS",          "FRED – Fed funds rate"),
    ("ECON DGS10",             "FRED – 10-year Treasury yield"),
    ("ECON DGS2",              "FRED – 2-year Treasury yield"),
    ("ECON SPREAD",            "FRED – 10Y-2Y yield spread"),
    ("ECON M2",                "FRED – M2 money supply"),
    ("ECON INDPRO",            "FRED – industrial production"),
    ("ECON RETAIL",            "FRED – retail sales"),
    ("ECON HOUSING",           "FRED – housing starts"),
    ("FRED CPIAUCSL",          "FRED raw series – CPI all items"),
    ("FRED UNRATE",            "FRED raw series – unemployment"),
    ("FRED DGS10",             "FRED raw series – 10Y yield"),
    # Watchlist
    ("WL",                     "Watchlist dashboard"),
    ("WL ADD AAPL",            "Add AAPL to watchlist"),
    ("WL ADD TSLA Tech",       "Add TSLA with label"),
    ("WL REMOVE AAPL",         "Remove AAPL from watchlist"),
    # Earnings
    ("EARN",                   "Earnings calendar for watchlist"),
    ("EARN AAPL",              "AAPL earnings detail + EPS history"),
    ("EARN TSLA",              "TSLA earnings detail"),
    ("EARN NVDA",              "NVDA earnings detail"),
    # Economic calendar
    ("ECAL",                   "Economic calendar – FOMC, CPI, NFP, GDP…"),
    # P&L
    ("PNL",                    "Portfolio P&L dashboard"),
    ("PNL ADD AAPL 100 150",   "Add 100 AAPL shares @ $150 cost"),
    ("PNL ADD TSLA 50 200",    "Add 50 TSLA shares @ $200 cost"),
    ("PNL REMOVE AAPL",        "Remove AAPL position"),
    # Correlation
    ("CORR",                   "Correlation matrix for watchlist (1Y)"),
    ("CORR AAPL MSFT NVDA",    "Correlation – AAPL vs MSFT vs NVDA"),
    ("CORR SPY QQQ IWM 1y",    "Correlation – ETFs, 1-year"),
    ("CORR AAPL MSFT 6mo",     "Correlation – 6-month lookback"),
    # Volatility
    ("VOL",                    "VIX dashboard + sector ETF realised vol"),
    ("VOL AAPL",               "AAPL full vol: RV, IV, distribution, surface"),
    ("VOL TSLA",               "TSLA volatility analysis"),
    ("VOL NVDA 6mo",           "NVDA vol – 6-month lookback"),
    ("VOL SPY 1y",             "SPY vol – 1-year lookback"),
    # Price alerts
    ("LIST ALERT",             "Show all active price alerts"),
    ("AAPL ADD_ALERT EVERY 2%","Alert every 2% move in AAPL"),
    ("TSLA ADD_ALERT EVERY 5%","Alert every 5% move in TSLA"),
    ("AAPL REMOVE_ALERT",      "Remove all AAPL price alerts"),
    ("TOP",                    "Today's top market news + sentiment (all categories)"),
    ("TOP",                    "Breaking market headlines — earnings, macro, crypto, IPO"),
    ("ANR TSLA",               "TSLA analyst ratings + price targets"),
    ("ANR NVDA",               "NVDA analyst ratings + price targets"),
    ("RV AAPL",                "AAPL relative value vs sector peers"),
    ("RV AAPL MSFT GOOGL",     "AAPL vs MSFT vs GOOGL valuation multiples"),
    ("RV TSLA",                "TSLA relative value vs peers"),
    # Market events
    ("IPO",                    "IPO calendar — upcoming & recent"),
    ("INSIDER AAPL",           "AAPL insider buying/selling"),
    ("INSIDER TSLA",           "TSLA insider transactions"),
    ("SHORT AAPL",             "AAPL short interest + squeeze gauge"),
    ("SHORT GME",              "GME short interest + squeeze gauge"),
    ("SHORT TSLA",             "TSLA short interest"),
    # Return & risk
    ("TRA AAPL",               "AAPL total return vs SPY + QQQ (3Y)"),
    ("TRA TSLA SPY QQQ",       "TSLA total return vs SPY + QQQ"),
    ("TRA AAPL SPY 5y",        "AAPL total return 5-year"),
    ("RISK AAPL",              "AAPL risk: beta, alpha, VaR, scatter (3Y)"),
    ("RISK TSLA QQQ",          "TSLA risk vs QQQ benchmark"),
    ("RISK NVDA SPY",          "NVDA risk vs SPY"),
    # Index & Fixed Income
    ("IND",                    "Index lookup — all major indices"),
    ("IND SPX",                "Index lookup — S&P 500 detail"),
    ("IND ^GSPC",              "Index lookup — by yahoo symbol"),
    ("WB",                     "World bond yields (10Y government)"),
    ("OAS",                    "Credit spread dashboard — all ratings"),
    ("OAS IG",                 "IG Corp OAS — credit risk gauge"),
    ("OAS HY",                 "High Yield OAS"),
    ("OAS AAA",                "AAA-rated OAS"),
    ("OAS BBB",                "BBB-rated OAS"),
    ("OAS BB",                 "BB-rated (high yield) OAS"),
    ("OASD",                   "OAS duration — spread by maturity bucket"),
    ("OASD IG",                "IG OAS across all maturity buckets"),
    ("OASD HY",                "High Yield OAS duration"),
    ("OASD 1-3Y",              "Short-end OAS history"),
    ("OASD 10-15Y",            "Long-end OAS history"),
    # Misc
    ("HELP",                   "Show full command reference"),
]
# Flat list for quick lookup
_ALL_CMDS = [c for c, _ in COMMAND_SUGGESTIONS]

# ── Data fetch helpers ─────────────────────────────────────────────────────────

@st.cache_data(ttl=60, show_spinner=False)
def _yf_ticker(symbol: str):
    if not _YF_OK: return None
    try: return yf.Ticker(symbol)
    except: return None

@st.cache_data(ttl=60, show_spinner=False)
def _fmt_large_pdf(v):
    """Format large numbers for PDF export."""
    if not v: return '—'
    try:
        v = float(v)
        if v >= 1e12: return f"${v/1e12:.2f}T"
        if v >= 1e9:  return f"${v/1e9:.2f}B"
        if v >= 1e6:  return f"${v/1e6:.1f}M"
        return f"${v:,.0f}"
    except:
        return '—'


def _yf_history(symbol: str, period: str = '1y', interval: str = '1d'):
    if not _YF_OK: return pd.DataFrame()
    try:
        t = yf.Ticker(symbol)
        df = t.history(period=period, interval=interval, auto_adjust=True)
        if df.empty: return pd.DataFrame()
        # yfinance emits a placeholder bar for the session currently in progress:
        # OHLC are NaN but Volume is already populated, so dropna(how='all')
        # will NOT remove it. Drop every row with a missing Close instead —
        # otherwise each downstream `iloc[-1]` reads a NaN and renders "nan" /
        # "+nan%" (observed on ^GSPC / ^IXIC / ^DJI before the US open).
        df = df[df['Close'].notna()]
        if df.empty: return pd.DataFrame()
        df.index = pd.to_datetime(df.index)
        if df.index.tz is not None:
            df.index = df.index.tz_convert('UTC').tz_localize(None)
        return df
    except Exception as e:
        return pd.DataFrame()

@st.cache_data(ttl=120, show_spinner=False)
def _yf_last_prev(symbol: str):
    """Return (last_price, previous_close) for a symbol, or (None, None)."""
    if not _YF_OK: return None, None
    try:
        fi = yf.Ticker(symbol).fast_info
        last = getattr(fi, 'last_price', None)
        prev = getattr(fi, 'previous_close', None)
        if last is None or prev is None: return None, None
        return float(last), float(prev)
    except Exception:
        return None, None

def _us_session():
    """US cash-equity session label: PRE / OPEN / AH / CLOSED.

    Time-based (America/New_York). PRE also covers Sunday-evening futures
    reopen ahead of the Monday cash open.
    """
    if ZoneInfo is None:
        return None
    try:
        now = datetime.now(ZoneInfo('America/New_York'))
    except Exception:
        return None
    wd   = now.weekday()          # Mon=0 … Sun=6
    mins = now.hour * 60 + now.minute
    if wd == 6:                   # Sunday — futures re-open 18:00 ET
        return 'PRE' if mins >= 18 * 60 else 'CLOSED'
    if wd == 5:                   # Saturday
        return 'CLOSED'
    if 4 * 60 <= mins < 9 * 60 + 30:
        return 'PRE'
    if 9 * 60 + 30 <= mins < 16 * 60:
        return 'OPEN'
    if 16 * 60 <= mins < 20 * 60:
        return 'AH'
    return 'CLOSED'

# Exchange timezone per cash index — used for session-aware day changes.
INDEX_TZ = {
    '^GSPC': 'America/New_York', '^IXIC': 'America/New_York',
    '^DJI': 'America/New_York',  '^RUT': 'America/New_York',
    '^VIX': 'America/New_York',  '^MOVE': 'America/New_York',
    '^FTSE': 'Europe/London',    '^GDAXI': 'Europe/Berlin',
    '^FCHI': 'Europe/Paris',     '^N225': 'Asia/Tokyo',
    '^HSI': 'Asia/Hong_Kong',    '000001.SS': 'Asia/Shanghai',
    '^AXJO': 'Australia/Sydney', '^KS11': 'Asia/Seoul',
}

@st.cache_data(ttl=120, show_spinner=False)
def _intraday_sessions(symbol: str) -> dict:
    """{session date (exchange-local): last 5-minute close} for the past 5 days."""
    if not _YF_OK: return {}
    try:
        h = yf.Ticker(symbol).history(period='5d', interval='5m', auto_adjust=False)
        h = h[h['Close'].notna()]
        if h.empty: return {}
        tz = INDEX_TZ.get(symbol)
        if tz and ZoneInfo is not None:
            if h.index.tz is None:
                h.index = h.index.tz_localize('UTC').tz_convert(tz)
            else:
                h.index = h.index.tz_convert(tz)
        sessions = h.groupby(h.index.date)['Close'].last()
        return {d: float(v) for d, v in sessions.items()}
    except Exception:
        return {}

def _last_two_sessions(symbol: str, closes) -> tuple:
    """(last, prev, last session date) using that exchange's own calendar.

    Comparing the final two *daily* rows is only correct when no session is
    missing between them. yfinance sometimes drops a session for cash indices
    (^GSPC 2026-10-21 while SPY traded that day): the pair then spans two
    sessions and the printed day change is roughly halved. If a weekday is
    absent between the last two daily bars, rebuild the previous close from
    5-minute bars; a real holiday simply has no intraday session, so nothing
    changes.
    """
    last = float(closes.iloc[-1])
    prev = float(closes.iloc[-2])
    d_last = pd.Timestamp(closes.index[-1]).date()
    d_prev = pd.Timestamp(closes.index[-2]).date()
    if d_last > d_prev:
        missing = list(pd.bdate_range(d_prev, d_last))[1:-1]
        if missing:
            sessions = _intraday_sessions(symbol)
            between = [d for d in sessions if d_prev < d < d_last]
            if between:
                d_prev = max(between)
                prev = sessions[d_prev]
    return last, prev, d_last

@st.cache_data(ttl=120, show_spinner=False)
def _futures_since_cash_close(fut_symbol: str, close_date) -> tuple:
    """(last futures price, % move since the 16:00 ET cash close).

    A futures *daily* change is measured from the previous settlement, while
    the cash close on screen already contains that move — applying one to the
    other double-counts the session. The overnight move is what happened after
    16:00 ET, which is what an implied open should carry.
    """
    if not _YF_OK: return None, None
    try:
        tz = ZoneInfo('America/New_York') if ZoneInfo is not None else None
        h = yf.Ticker(fut_symbol).history(period='2d', interval='5m', auto_adjust=False)
        h = h[h['Close'].notna()]
        if h.empty: return None, None
        if tz is not None:
            h.index = (h.index.tz_localize('UTC').tz_convert(tz) if h.index.tz is None
                       else h.index.tz_convert(tz))
        last = float(h['Close'].iloc[-1])
        target = pd.Timestamp(close_date)
        target = target.tz_localize(tz) if (tz is not None and target.tz is None) else target
        target = target.replace(hour=16, minute=0, second=0)
        base_rows = h[h.index <= target]
        if base_rows.empty: return last, None
        base = float(base_rows['Close'].iloc[-1])
        if not base: return last, None
        return last, (last - base) / base * 100
    except Exception:
        return None, None


@st.cache_data(ttl=300, show_spinner=False)
def _yf_info(symbol: str) -> dict:
    if not _YF_OK: return {}
    try:
        t = yf.Ticker(symbol)
        return t.info or {}
    except: return {}

@st.cache_data(ttl=300, show_spinner=False)
def _yf_news(symbol: str) -> list:
    if not _YF_OK: return []
    try:
        from chat import _yf_news_items
        return _yf_news_items(symbol, limit=15)
    except: return []

@st.cache_data(ttl=600, show_spinner=False)
def _yf_financials(symbol: str):
    if not _YF_OK: return {}, {}, {}
    try:
        t = yf.Ticker(symbol)
        return t.financials, t.balance_sheet, t.cashflow
    except: return {}, {}, {}

@st.cache_data(ttl=600, show_spinner=False)
def _yf_options_chain(symbol: str):
    if not _YF_OK: return [], None, None
    try:
        t = yf.Ticker(symbol)
        dates = t.options
        if not dates: return [], None, None
        chain = t.option_chain(dates[0])
        return list(dates), chain.calls, chain.puts
    except: return [], None, None

@st.cache_data(ttl=300, show_spinner=False)
def _yf_dividends(symbol: str):
    if not _YF_OK: return pd.Series()
    try:
        t = yf.Ticker(symbol)
        return t.dividends
    except: return pd.Series()

@st.cache_data(ttl=900, show_spinner=False)
def _fetch_fred(series_id: str, fred_api_key: str = '', limit: int = 120) -> pd.DataFrame:
    """Fetch from FRED. Works without API key for public series (via HTML fallback)."""
    try:
        base = 'https://fred.stlouisfed.org/graph/fredgraph.csv'
        params = {'id': series_id}
        if fred_api_key:
            params['api_key'] = fred_api_key
        r = requests.get(base, params=params, timeout=10)
        if r.status_code == 200:
            from io import StringIO
            df = pd.read_csv(StringIO(r.text), parse_dates=['DATE'])
            df = df.rename(columns={'DATE': 'Date', series_id: 'Value'})
            df = df.dropna()
            df['Value'] = pd.to_numeric(df['Value'], errors='coerce')
            df = df.dropna()
            return df.tail(limit)
    except: pass
    # Fallback: FRED JSON API (no key required for most series)
    try:
        url = f'https://api.stlouisfed.org/fred/series/observations'
        params = {'series_id': series_id, 'file_type': 'json',
                  'observation_start': '2000-01-01', 'sort_order': 'desc',
                  'limit': limit}
        if fred_api_key: params['api_key'] = fred_api_key
        r = requests.get(url, params=params, timeout=10)
        if r.status_code == 200:
            obs = r.json().get('observations', [])
            df  = pd.DataFrame(obs)[['date','value']].rename(
                    columns={'date':'Date','value':'Value'})
            df['Date']  = pd.to_datetime(df['Date'])
            df['Value'] = pd.to_numeric(df['Value'], errors='coerce')
            df = df.dropna().sort_values('Date')
            return df
    except: pass
    return pd.DataFrame()

@st.cache_data(ttl=300, show_spinner=False)
def _fetch_av_news(ticker: str, av_key: str) -> list:
    """Alpha Vantage news sentiment (requires free API key)."""
    if not av_key: return []
    try:
        url = 'https://www.alphavantage.co/query'
        params = {'function': 'NEWS_SENTIMENT', 'tickers': ticker,
                  'limit': 10, 'apikey': av_key}
        r = requests.get(url, params=params, timeout=10)
        if r.status_code == 200:
            return r.json().get('feed', [])
    except: pass
    return []

@st.cache_data(ttl=300, show_spinner=False)
def _fetch_newsapi(query: str, newsapi_key: str, category: str = '',
                   page_size: int = 20) -> list:
    """
    NewsAPI.org – primary news source.
    - Uses /v2/top-headlines for category-based news (business, technology, general…)
    - Uses /v2/everything for free-text or ticker-based queries.
    Returns a list of article dicts with: title, source, publishedAt, url, description.
    Requires a free NewsAPI key from https://newsapi.org/register
    """
    if not newsapi_key:
        return []
    try:
        base = 'https://newsapi.org/v2'
        headers = {'X-Api-Key': newsapi_key}

        NEWSAPI_CATEGORIES = {'business', 'technology', 'science',
                               'health', 'entertainment', 'sports', 'general'}

        if category and category.lower() in NEWSAPI_CATEGORIES:
            # Top headlines by category
            params = {'category': category.lower(), 'language': 'en',
                      'pageSize': page_size}
            r = requests.get(f'{base}/top-headlines', headers=headers,
                             params=params, timeout=10)
        elif query:
            # Everything search — use for ticker queries and free-text
            params = {'q': query, 'language': 'en', 'sortBy': 'publishedAt',
                      'pageSize': page_size}
            r = requests.get(f'{base}/everything', headers=headers,
                             params=params, timeout=10)
        else:
            # Default: top business headlines
            params = {'category': 'business', 'language': 'en',
                      'pageSize': page_size}
            r = requests.get(f'{base}/top-headlines', headers=headers,
                             params=params, timeout=10)

        if r.status_code == 200:
            articles = r.json().get('articles', [])
            return [
                {
                    'title':       a.get('title', ''),
                    'source':      (a.get('source') or {}).get('name', ''),
                    'publishedAt': a.get('publishedAt', ''),
                    'url':         a.get('url', ''),
                    'description': a.get('description') or '',
                }
                for a in articles
                if a.get('title') and a.get('title') != '[Removed]'
            ]
        elif r.status_code == 401:
            st.warning("NewsAPI key is invalid. Please check it in Terminal → API Keys.")
        elif r.status_code == 426:
            st.warning("NewsAPI free plan only supports headlines. Upgrade at newsapi.org for full search.")
    except Exception:
        pass
    return []


def _fmt_newsapi_dt(iso: str) -> str:
    """Format ISO 8601 datetime string from NewsAPI to readable form."""
    if not iso:
        return '—'
    try:
        dt = datetime.strptime(iso[:19], '%Y-%m-%dT%H:%M:%S')
        return dt.strftime('%d %b %Y  %H:%M')
    except Exception:
        return iso[:10]


@st.cache_data(ttl=600, show_spinner=False)
def _fetch_fmp_profile(ticker: str, fmp_key: str) -> dict:
    """FMP company profile (requires free API key)."""
    if not fmp_key: return {}
    try:
        url = f'https://financialmodelingprep.com/api/v3/profile/{ticker}'
        r = requests.get(url, params={'apikey': fmp_key}, timeout=10)
        if r.status_code == 200:
            data = r.json()
            return data[0] if data else {}
    except: pass
    return {}

@st.cache_data(ttl=300, show_spinner=False)
def _fetch_alpaca_bars(ticker: str, ak: str, as_: str) -> pd.DataFrame:
    """Alpaca Markets bar data (requires free paper account keys)."""
    if not ak or not as_: return pd.DataFrame()
    try:
        end   = datetime.utcnow()
        start = end - timedelta(days=30)
        url   = f'https://data.alpaca.markets/v2/stocks/{ticker}/bars'
        headers = {'APCA-API-KEY-ID': ak, 'APCA-API-SECRET-KEY': as_}
        params  = {'timeframe': '1Day', 'start': start.strftime('%Y-%m-%d'),
                   'end': end.strftime('%Y-%m-%d'), 'limit': 30}
        r = requests.get(url, headers=headers, params=params, timeout=10)
        if r.status_code == 200:
            bars = r.json().get('bars', [])
            if bars:
                df = pd.DataFrame(bars)
                df['t'] = pd.to_datetime(df['t'])
                df = df.rename(columns={'t':'Date','o':'Open','h':'High',
                                        'l':'Low','c':'Close','v':'Volume'})
                return df.set_index('Date')
    except: pass
    return pd.DataFrame()

def _fmt_large(v):
    if v is None or (isinstance(v, float) and np.isnan(v)): return '—'
    abs_v = abs(v)
    if abs_v >= 1e12: return f"${v/1e12:.2f}T"
    if abs_v >= 1e9:  return f"${v/1e9:.2f}B"
    if abs_v >= 1e6:  return f"${v/1e6:.2f}M"
    return f"${v:,.0f}"

def _chg_html(val, pct=True):
    if val is None: return '<span class="term-neu">—</span>'
    sfx = '%' if pct else ''
    if val > 0:  return f'<span class="term-up">▲ {val:+.2f}{sfx}</span>'
    if val < 0:  return f'<span class="term-dn">▼ {val:+.2f}{sfx}</span>'
    return f'<span class="term-neu">— {val:.2f}{sfx}</span>'

def _safe_get(d, *keys, default=None):
    for k in keys:
        if isinstance(d, dict) and k in d:
            v = d[k]
            if v is not None and not (isinstance(v, float) and np.isnan(v)):
                return v
    return default

# ── FMP helpers ────────────────────────────────────────────────────────────────

def _fmp_get(endpoint: str, fmp_key: str, params: dict = None) -> dict | list | None:
    """Generic FMP API call. Returns parsed JSON or None on failure."""
    if not fmp_key:
        return None
    try:
        p = {'apikey': fmp_key}
        if params:
            p.update(params)
        r = requests.get(f"https://financialmodelingprep.com/api{endpoint}",
                         params=p, timeout=10)
        if r.status_code == 200:
            data = r.json()
            # FMP returns [] or {} or {"Error Message":...} on bad key/limit
            if isinstance(data, dict) and 'Error Message' in data:
                return None
            return data
    except:
        pass
    return None


def _fmp_profile(ticker: str, fmp_key: str) -> dict:
    """FMP /v3/profile — rich company profile."""
    data = _fmp_get(f'/v3/profile/{ticker}', fmp_key)
    if data and isinstance(data, list) and len(data) > 0:
        return data[0]
    return {}


def _fmp_ratios(ticker: str, fmp_key: str) -> dict:
    """FMP /v3/ratios-ttm — TTM financial ratios."""
    data = _fmp_get(f'/v3/ratios-ttm/{ticker}', fmp_key)
    if data and isinstance(data, list) and len(data) > 0:
        return data[0]
    return {}


def _fmp_key_metrics(ticker: str, fmp_key: str, period: str = 'annual') -> list:
    """FMP /v3/key-metrics — annual or quarterly key metrics (up to 10Y)."""
    data = _fmp_get(f'/v3/key-metrics/{ticker}', fmp_key, {'period': period, 'limit': 12})
    return data if isinstance(data, list) else []


def _fmp_income(ticker: str, fmp_key: str, period: str = 'annual') -> list:
    """FMP /v3/income-statement — annual or quarterly."""
    data = _fmp_get(f'/v3/income-statement/{ticker}', fmp_key, {'period': period, 'limit': 12})
    return data if isinstance(data, list) else []


def _fmp_balance(ticker: str, fmp_key: str, period: str = 'annual') -> list:
    """FMP /v3/balance-sheet-statement."""
    data = _fmp_get(f'/v3/balance-sheet-statement/{ticker}', fmp_key, {'period': period, 'limit': 12})
    return data if isinstance(data, list) else []


def _fmp_cashflow(ticker: str, fmp_key: str, period: str = 'annual') -> list:
    """FMP /v3/cash-flow-statement."""
    data = _fmp_get(f'/v3/cash-flow-statement/{ticker}', fmp_key, {'period': period, 'limit': 12})
    return data if isinstance(data, list) else []


def _fmp_executives(ticker: str, fmp_key: str) -> list:
    """FMP /v3/key-executives."""
    data = _fmp_get(f'/v3/key-executives/{ticker}', fmp_key)
    return data if isinstance(data, list) else []


def _fmp_peers(ticker: str, fmp_key: str) -> list:
    """FMP /v4/stock_peers."""
    data = _fmp_get(f'/v4/stock_peers', fmp_key, {'symbol': ticker})
    if data and isinstance(data, list) and len(data) > 0:
        return data[0].get('peersList', [])
    return []


def _fmp_statements_to_df(rows: list, fields: list) -> pd.DataFrame:
    """Convert FMP statement list → pretty DataFrame (rows = years, cols = fields)."""
    if not rows:
        return pd.DataFrame()
    records = []
    for row in rows:
        rec = {'Period': row.get('date', row.get('calendarYear', ''))[:10]}
        for f in fields:
            v = row.get(f)
            rec[f] = float(v) / 1e6 if v is not None else None   # → $M
        records.append(rec)
    df = pd.DataFrame(records).set_index('Period')
    return df


def _src_badge(label: str, color: str) -> str:
    return (f"<span style='font-family:monospace;font-size:9px;color:{color};"
            f"border:1px solid {color};padding:0 4px;border-radius:2px;"
            f"margin-left:6px'>{label}</span>")

# ── Chart builders ─────────────────────────────────────────────────────────────

def _candlestick_chart(df: pd.DataFrame, title: str, height=500):
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        vertical_spacing=0.03, row_heights=[0.75, 0.25])
    fig.add_trace(go.Candlestick(
        x=df.index, open=df['Open'], high=df['High'],
        low=df['Low'],  close=df['Close'],
        name='OHLC',
        increasing_line_color='#00e676', decreasing_line_color='#ff1744',
        increasing_fillcolor='#00e676', decreasing_fillcolor='#ff1744',
    ), row=1, col=1)
    # Overlay EMAs
    for n, clr in [(20,'#ffb300'),(50,'#40c4ff'),(200,'#ce93d8')]:
        if len(df) >= n:
            fig.add_trace(go.Scatter(
                x=df.index, y=df['Close'].ewm(span=n).mean(),
                name=f'EMA{n}', line=dict(color=clr, width=1.2), opacity=0.85
            ), row=1, col=1)
    # Volume bars
    vol_colors = ['#00e676' if c >= o else '#ff1744'
                  for c, o in zip(df['Close'], df['Open'])]
    if 'Volume' in df.columns:
        fig.add_trace(go.Bar(
            x=df.index, y=df['Volume'], name='Volume',
            marker_color=vol_colors, opacity=0.6
        ), row=2, col=1)
    fig.update_layout(
        title=dict(text=title, font=dict(color=T['amber'], size=14)),
        paper_bgcolor=T['bg'], plot_bgcolor=T['panel'],
        font=dict(color=T['white'], family='monospace'),
        xaxis_rangeslider_visible=False,
        height=height, hovermode='x unified',
        legend=dict(orientation='h', y=1.06, x=0,
                    font=dict(size=10)),
        margin=dict(l=10, r=10, t=50, b=10),
    )
    fig.update_xaxes(gridcolor=T['border'], zeroline=False)
    fig.update_yaxes(gridcolor=T['border'], zeroline=False)
    return fig

def _to_rgba(clr: str, alpha: float = 0.08) -> str:
    """Convert any CSS colour (hex or rgb/rgba) to a valid rgba(...) string."""
    clr = clr.strip()
    if clr.startswith('rgba('):
        parts = clr[5:-1].split(',')
        return f"rgba({','.join(parts[:3])},{alpha})"
    if clr.startswith('rgb('):
        return clr.replace('rgb(', 'rgba(').replace(')', f',{alpha})')
    # Hex: #rgb or #rrggbb
    h = clr.lstrip('#')
    if len(h) == 3:
        h = ''.join(c * 2 for c in h)
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"

def _line_chart_term(x, y, title, y_label='Value', color=None, height=350):
    clr = color or T['amber']
    fig = go.Figure(go.Scatter(
        x=x, y=y, mode='lines', line=dict(color=clr, width=2),
        fill='tozeroy', fillcolor=_to_rgba(clr, 0.08),
        hovertemplate='%{x|%Y-%m-%d}<br>' + y_label + ': %{y:,.2f}<extra></extra>',
    ))
    fig.update_layout(
        title=dict(text=title, font=dict(color=T['amber'], size=13)),
        paper_bgcolor=T['bg'], plot_bgcolor=T['panel'],
        font=dict(color=T['white'], family='monospace'),
        height=height,
        xaxis=dict(gridcolor=T['border']),
        yaxis=dict(gridcolor=T['border'], title=y_label),
        margin=dict(l=10, r=10, t=45, b=10),
        hovermode='x unified',
    )
    return fig

def _bar_chart_term(labels, values, title, height=350):
    colors_bar = [T['green'] if v >= 0 else T['red'] for v in values]
    fig = go.Figure(go.Bar(
        x=labels, y=values, marker_color=colors_bar,
        text=[f"{v:+.2f}%" for v in values], textposition='outside',
        textfont=dict(size=10),
    ))
    fig.add_hline(y=0, line_color=T['muted'], opacity=0.5)
    fig.update_layout(
        title=dict(text=title, font=dict(color=T['amber'], size=13)),
        paper_bgcolor=T['bg'], plot_bgcolor=T['panel'],
        font=dict(color=T['white'], family='monospace'),
        height=height, xaxis_tickangle=-30,
        margin=dict(l=10, r=10, t=45, b=60),
        xaxis=dict(gridcolor=T['border']),
        yaxis=dict(gridcolor=T['border']),
    )
    return fig

# ── Command implementations ────────────────────────────────────────────────────

def _cmd_search(query: str):
    """SEARCH <query> — find tickers/companies via Yahoo Finance search."""
    st.markdown(f"<div class='term-header'>🔍  SEARCH — {query.upper() if query else '…'}</div>",
                unsafe_allow_html=True)
    if not query.strip():
        st.info("Usage:  `SEARCH apple`   |   `SEARCH TSL`   |   `SEARCH semiconductor`")
        return
    try:
        resp = requests.get(
            "https://query2.finance.yahoo.com/v1/finance/search",
            params={'q': query, 'quotesCount': 20, 'newsCount': 0, 'listsCount': 0,
                    'enableFuzzyQuery': True},
            headers={'User-Agent': 'Mozilla/5.0'},
            timeout=6,
        )
        quotes = resp.json().get('quotes', [])
    except Exception as e:
        st.error(f"Search unavailable: {e}"); return

    if not quotes:
        st.warning(f"No results found for **{query}**."); return

    keep = {'EQUITY','ETF','INDEX','MUTUALFUND','CRYPTOCURRENCY'}
    rows = [q for q in quotes if (q.get('quoteType','').upper()) in keep]
    if not rows:
        st.warning(f"No equity/ETF results for **{query}**."); return

    st.markdown(
        f"<div style='font-family:monospace;font-size:12px;color:{T['muted']};margin-bottom:8px'>"
        f"<b style='color:{T['amber']}'>{len(rows)}</b> result(s) — click ▶ to open overview</div>",
        unsafe_allow_html=True)

    type_colors = {'Equity': T['green'], 'Etf': T['blue'], 'Index': T['amber'],
                   'Mutualfund': '#ce93d8', 'Cryptocurrency': T['red']}
    card_cols = st.columns(2)
    for i, q in enumerate(rows):
        sym   = q.get('symbol', '—')
        name  = (q.get('shortname') or q.get('longname') or '—')[:45]
        qtype = (q.get('quoteType') or '').title()
        exch  = q.get('exchDisp') or q.get('exchange') or '—'
        sector= q.get('sector') or q.get('industry') or '—'
        clr   = type_colors.get(qtype, T['muted'])
        col   = card_cols[i % 2]
        col.markdown(
            f"<div class='term-panel' style='padding:8px 12px;margin-bottom:5px'>"
            f"<span style='color:{T['amber']};font-family:monospace;font-weight:bold;font-size:15px'>{sym}</span>"
            f"<span style='color:{clr};font-family:monospace;font-size:10px;"
            f"border:1px solid {clr};padding:1px 5px;border-radius:3px;margin-left:8px'>{qtype}</span>"
            f"<span style='color:{T['muted']};font-family:monospace;font-size:10px;margin-left:6px'>{exch}</span><br>"
            f"<span style='color:{T['white']};font-family:monospace;font-size:12px'>{name}</span><br>"
            f"<span style='color:{T['muted']};font-family:monospace;font-size:10px'>{sector}</span>"
            f"</div>", unsafe_allow_html=True)
        if col.button(f"▶ {sym}", key=f"srch_{i}_{sym}", use_container_width=True):
            ss = st.session_state
            ss.term_cmd = sym; ss['_cmd_val'] = sym
            ss['_input_gen'] = ss.get('_input_gen', 0) + 1
            ss['_should_run'] = True
            ss.term_history.append(sym)
            st.rerun()


def cmd_overview(ticker: str, api_keys: dict):
    """Default overview for a security — price + key stats + mini chart."""
    fmp_key = api_keys.get('fmp', '')

    info = _yf_info(ticker)
    if not info:
        st.error(f"❌ No data found for **{ticker}**. Check the symbol and try again.")
        return

    # Fetch FMP profile + ratios in parallel
    fmp_profile  = _fmp_profile(ticker, fmp_key)   if fmp_key else {}
    fmp_ratios   = _fmp_ratios(ticker, fmp_key)     if fmp_key else {}

    # Price — prefer yfinance real-time
    name  = _safe_get(info, 'longName', 'shortName', default=ticker)
    price = _safe_get(info, 'currentPrice', 'regularMarketPrice', 'previousClose', default=0)
    prev  = _safe_get(info, 'previousClose', 'regularMarketPreviousClose', default=price)
    chg   = price - prev
    chg_p = (chg / prev * 100) if prev else 0

    # FMP can fill name/sector/industry if yf is blank
    if fmp_profile:
        name = name or fmp_profile.get('companyName', ticker)

    color_cls = 'term-up' if chg >= 0 else 'term-dn'
    arrow = '▲' if chg >= 0 else '▼'

    # Source badges
    yf_badge  = _src_badge('yfinance', T['muted'])
    fmp_badge = _src_badge('FMP', T['green']) if fmp_profile else ''

    st.markdown(f"""
<div class="term-panel">
  <div style="font-family:monospace; color:{T['amber']}; font-size:22px; font-weight:bold;">
    {ticker.upper()} &nbsp;|&nbsp;
    <span style="color:{T['white']}">{name}</span>
    {yf_badge}{fmp_badge}
  </div>
  <div style="font-family:monospace; font-size:28px; color:{T['white']}; margin-top:4px;">
    {price:,.4f}
    &nbsp;<span class="{color_cls}">{arrow} {chg:+.4f} ({chg_p:+.2f}%)</span>
  </div>
  <div class="term-lbl" style="margin-top:4px;">
    Exchange: {fmp_profile.get('exchangeShortName') or _safe_get(info,'exchange',default='—')} &nbsp;|&nbsp;
    Currency: {fmp_profile.get('currency') or _safe_get(info,'currency',default='—')} &nbsp;|&nbsp;
    Sector: {fmp_profile.get('sector') or _safe_get(info,'sector',default='—')} &nbsp;|&nbsp;
    Industry: {fmp_profile.get('industry') or _safe_get(info,'industry',default='—')} &nbsp;|&nbsp;
    Country: {fmp_profile.get('country') or _safe_get(info,'country',default='—')}
  </div>
</div>""", unsafe_allow_html=True)

    # ── Key stats — merge yf + FMP, FMP fills gaps & adds extra fields ────────
    def _v(*keys_and_sources):
        """Try each (source_dict, key) pair, return first non-None."""
        for src, key in keys_and_sources:
            v = src.get(key) if isinstance(src, dict) else None
            if v is not None and not (isinstance(v, float) and np.isnan(v)):
                return v
        return None

    mkt_cap  = _v((info,'marketCap'), (fmp_profile,'mktCap'))
    revenue  = _v((info,'totalRevenue'), (fmp_ratios,'revenuePerShareTTM'))
    ebitda   = _v((info,'ebitda'), (fmp_ratios,'ebitdaPerShareTTM'))
    fcf      = _v((info,'freeCashflow'), (fmp_ratios,'freeCashFlowPerShareTTM'))

    stats = [
        ('Open',           _safe_get(info,'open','regularMarketOpen')),
        ('Prev Close',     _safe_get(info,'previousClose')),
        ('Day High',       _safe_get(info,'dayHigh','regularMarketDayHigh')),
        ('Day Low',        _safe_get(info,'dayLow','regularMarketDayLow')),
        ('52W High',       _safe_get(info,'fiftyTwoWeekHigh')),
        ('52W Low',        _safe_get(info,'fiftyTwoWeekLow')),
        ('Volume',         _safe_get(info,'volume','regularMarketVolume')),
        ('Avg Volume',     _safe_get(info,'averageVolume')),
        ('Market Cap',     mkt_cap),
        ('Shares Out',     _safe_get(info,'sharesOutstanding')),
        # Valuation — FMP fills when yf is None
        ('P/E (TTM)',      _v((info,'trailingPE'),          (fmp_ratios,'peRatioTTM'))),
        ('Fwd P/E',        _v((info,'forwardPE'),           (fmp_ratios,'forwardPERatioTTM'))),
        ('P/B Ratio',      _v((info,'priceToBook'),         (fmp_ratios,'pbRatioTTM'))),
        ('P/S Ratio',      _v((info,'priceToSalesTrailing12Months'), (fmp_ratios,'priceToSalesRatioTTM'))),
        ('EV/EBITDA',      _v((info,'enterpriseToEbitda'), (fmp_ratios,'enterpriseValueOverEBITDATTM'))),
        ('PEG Ratio',      _v((info,'pegRatio'),            (fmp_ratios,'pegRatioTTM'))),
        ('EPS (TTM)',      _v((info,'trailingEps'),         (fmp_ratios,'netIncomePerShareTTM'))),
        ('Fwd EPS',        _safe_get(info,'forwardEps')),
        # Quality — FMP ratios are often richer
        ('Gross Margin',   _v((info,'grossMargins'),        (fmp_ratios,'grossProfitMarginTTM'))),
        ('Net Margin',     _v((info,'profitMargins'),       (fmp_ratios,'netProfitMarginTTM'))),
        ('ROE',            _v((info,'returnOnEquity'),      (fmp_ratios,'returnOnEquityTTM'))),
        ('ROA',            _v((info,'returnOnAssets'),      (fmp_ratios,'returnOnAssetsTTM'))),
        ('ROIC',           fmp_ratios.get('returnOnCapitalEmployedTTM')),
        ('Debt/Equity',    _v((info,'debtToEquity'),        (fmp_ratios,'debtEquityRatioTTM'))),
        ('Current Ratio',  _v((info,'currentRatio'),        (fmp_ratios,'currentRatioTTM'))),
        ('Quick Ratio',    _v((info,'quickRatio'),          (fmp_ratios,'quickRatioTTM'))),
        ('Beta',           _v((info,'beta'),                (fmp_profile,'beta'))),
        ('Div Yield',      _v((info,'dividendYield'),       (fmp_ratios,'dividendYieldTTM'))),
        ('Revenue (TTM)',  _safe_get(info,'totalRevenue')),
        ('EBITDA',         _safe_get(info,'ebitda')),
        ('Free Cash Flow', _safe_get(info,'freeCashflow')),
        ('IPO Date',       fmp_profile.get('ipoDate')),
    ]

    pct_fields = {'Gross Margin','Net Margin','ROE','ROA','ROIC','Div Yield'}
    large_fields = {'Market Cap','Revenue (TTM)','EBITDA','Free Cash Flow','Shares Out','Volume','Avg Volume'}

    cols = st.columns(4)
    for i, (lbl, val) in enumerate(stats):
        col = cols[i % 4]
        if val is None:
            disp = '—'
        elif lbl in large_fields:
            disp = _fmt_large(float(val))
        elif lbl in pct_fields:
            v = float(val)
            disp = f"{v*100:.2f}%" if abs(v) < 10 else f"{v:.2f}%"
        elif lbl == 'IPO Date':
            disp = str(val)
        else:
            disp = f"{float(val):,.4f}" if isinstance(val, float) else str(val)
        col.markdown(
            f'<div class="term-ticker"><span class="term-lbl">{lbl}</span><br>'
            f'<span class="term-val">{disp}</span></div>',
            unsafe_allow_html=True)

    # ── FMP extra: DCF + analyst price target ─────────────────────────────────
    if fmp_key:
        dcf_data = _fmp_get(f'/v3/discounted-cash-flow/{ticker}', fmp_key)
        if dcf_data and isinstance(dcf_data, list) and dcf_data:
            dcf = dcf_data[0]
            dcf_val  = dcf.get('dcf')
            dcf_upside = ((float(dcf_val) - price) / price * 100) if dcf_val and price else None
            st.markdown("---")
            d1, d2, d3 = st.columns(3)
            d1.metric("FMP DCF Value",    f"${float(dcf_val):,.2f}" if dcf_val else "—",
                      delta=f"{dcf_upside:+.1f}% vs current" if dcf_upside else None)
            target = _safe_get(info,'targetMeanPrice')
            rec    = _safe_get(info,'recommendationKey')
            if target:
                upside = ((float(target) - price) / price * 100) if price else 0
                d2.metric("Analyst Target", f"${float(target):,.2f}",
                          delta=f"{upside:+.1f}% upside")
            if rec:
                d3.metric("Consensus", rec.replace('_',' ').title())

    # ── Mini 1Y chart ──────────────────────────────────────────────────────────
    st.markdown("---")
    df = _yf_history(ticker, period='1y')
    if not df.empty:
        st.plotly_chart(_candlestick_chart(df, f"{ticker} — 1 Year", height=480),
                        use_container_width=True)

    # Analyst targets (fallback when no FMP key)
    if not fmp_key:
        target = _safe_get(info,'targetMeanPrice')
        rec    = _safe_get(info,'recommendationKey')
        if target or rec:
            tc1, tc2, tc3 = st.columns(3)
            if target:
                upside = ((float(target) - price) / price * 100) if price else 0
                tc1.metric("Analyst Target", f"${float(target):,.2f}",
                           delta=f"{upside:+.1f}% upside")
            if rec:
                tc2.metric("Consensus", rec.replace('_',' ').title())
            num_analysts = _safe_get(info,'numberOfAnalystOpinions')
            if num_analysts:
                tc3.metric("# Analysts", str(int(num_analysts)))


def cmd_chart(ticker: str, period: str, api_keys: dict):
    period_map = {'1d':'1d','5d':'5d','1mo':'1mo','3mo':'3mo','6mo':'6mo',
                  '1y':'1y','2y':'2y','5y':'5y','10y':'10y','max':'max',
                  '1w':'5d','ytd':'ytd'}
    period = period_map.get(period.lower(), '1y')
    interval = '5m' if period == '1d' else ('1h' if period in ('5d','1mo') else '1d')
    df = _yf_history(ticker, period=period, interval=interval)
    if df.empty:
        st.error(f"No price data for {ticker}"); return
    info = _yf_info(ticker)
    name = _safe_get(info,'longName','shortName', default=ticker)
    st.plotly_chart(_candlestick_chart(df, f"{ticker} — {name} ({period})", height=600),
                    use_container_width=True)
    # Key stats below chart. Drop trailing empty bars first: yfinance publishes a
    # placeholder row for the current session on some feeds (US cash indices
    # before the open), so a raw iloc[-1] can be NaN and poison the metrics.
    _cl = df['Close'].dropna()
    if len(_cl) == 0:
        st.error(f"No usable closes for {ticker}"); return
    latest = _cl.iloc[-1]
    ret_1d = (_cl.iloc[-1]/_cl.iloc[-2]-1)*100 if len(_cl)>1 else 0
    ret_tot = (_cl.iloc[-1]/_cl.iloc[0]-1)*100
    vol = _cl.pct_change().std() * np.sqrt(252) * 100
    c1,c2,c3,c4 = st.columns(4)
    c1.metric("Latest Close", f"{latest:,.4f}")
    c2.metric("1D Change",    f"{ret_1d:+.2f}%")
    c3.metric(f"Period Return", f"{ret_tot:+.2f}%")
    c4.metric("Ann. Volatility", f"{vol:.1f}%")


def cmd_description(ticker: str, api_keys: dict):
    fmp_key = api_keys.get('fmp', '')
    info        = _yf_info(ticker)
    fmp_profile = _fmp_profile(ticker, fmp_key) if fmp_key else {}

    if not info and not fmp_profile:
        st.error(f"No data for {ticker}"); return

    name = (fmp_profile.get('companyName') or
            _safe_get(info, 'longName', 'shortName', default=ticker))
    st.markdown(f"<div class='term-header'>📋  {ticker.upper()} — {name} — DES</div>",
                unsafe_allow_html=True)

    # Description — FMP often has cleaner text
    bio = (fmp_profile.get('description') or
           _safe_get(info, 'longBusinessSummary', default='No description available.'))
    bio_src = _src_badge('FMP', T['green']) if fmp_profile.get('description') else _src_badge('yfinance', T['muted'])
    st.markdown(
        f'<div class="term-panel" style="color:{T["white"]};font-family:monospace;'
        f'font-size:12px;line-height:1.6">{bio} {bio_src}</div>',
        unsafe_allow_html=True)

    # Key facts — FMP fills more fields
    website = fmp_profile.get('website') or _safe_get(info, 'website')
    keys = [
        ('Website',     website),
        ('Country',     fmp_profile.get('country')        or _safe_get(info,'country')),
        ('City',        fmp_profile.get('city')           or _safe_get(info,'city')),
        ('Address',     fmp_profile.get('address')        or _safe_get(info,'address1')),
        ('Employees',   fmp_profile.get('fullTimeEmployees') or _safe_get(info,'fullTimeEmployees')),
        ('Sector',      fmp_profile.get('sector')         or _safe_get(info,'sector')),
        ('Industry',    fmp_profile.get('industry')       or _safe_get(info,'industry')),
        ('Exchange',    fmp_profile.get('exchangeShortName') or _safe_get(info,'exchange')),
        ('Currency',    fmp_profile.get('currency')       or _safe_get(info,'currency')),
        ('IPO Date',    fmp_profile.get('ipoDate')),
        ('CIK',         fmp_profile.get('cik')),
        ('ISIN',        fmp_profile.get('isin')           or _safe_get(info,'isin')),
        ('Fiscal Year', _safe_get(info,'fiscalYearEnd')),
        ('Auditor',     fmp_profile.get('auditor')),
    ]
    c1, c2, c3 = st.columns(3)
    shown = 0
    for lbl, val in keys:
        if val:
            [c1, c2, c3][shown % 3].markdown(
                f'<span class="term-lbl">{lbl}</span><br>'
                f'<span class="term-val">{val}</span>', unsafe_allow_html=True)
            shown += 1

    # ── FMP Key Executives ─────────────────────────────────────────────────
    if fmp_key:
        execs = _fmp_executives(ticker, fmp_key)
        if execs:
            st.markdown("---")
            st.markdown("**👔 Key Executives**")
            exec_rows = []
            for e in execs[:10]:
                exec_rows.append({
                    'Name':  e.get('name', '—'),
                    'Title': e.get('title', '—'),
                    'Pay':   f"${e['pay']:,.0f}" if e.get('pay') else '—',
                    'Year Born': str(e.get('yearBorn', '—')),
                })
            st.dataframe(pd.DataFrame(exec_rows), use_container_width=True, hide_index=True)

    # ── FMP Stock peers ───────────────────────────────────────────────────
    if fmp_key:
        peers = _fmp_peers(ticker, fmp_key)
        if peers:
            st.markdown(f"**🔗 FMP Peers:** " +
                        "  ".join(f"`{p}`" for p in peers[:10]))


def cmd_financials(ticker: str, api_keys: dict):
    fmp_key = api_keys.get('fmp', '')
    st.markdown(f"<div class='term-header'>💹  {ticker.upper()} — FINANCIALS (FA)</div>",
                unsafe_allow_html=True)

    # Period toggle (annual / quarterly)
    period = st.radio("Period", ['Annual', 'Quarterly'], horizontal=True,
                      key=f'fa_period_{ticker}').lower()[:1]   # 'a' or 'q'
    fmp_period = 'annual' if period == 'a' else 'quarter'

    # ── FMP statements (richer, longer history) ───────────────────────────
    fmp_inc  = _fmp_income(ticker, fmp_key, fmp_period)   if fmp_key else []
    fmp_bal  = _fmp_balance(ticker, fmp_key, fmp_period)  if fmp_key else []
    fmp_cf   = _fmp_cashflow(ticker, fmp_key, fmp_period) if fmp_key else []
    fmp_km   = _fmp_key_metrics(ticker, fmp_key, fmp_period) if fmp_key else []

    # ── yfinance fallback ─────────────────────────────────────────────────
    yf_income, yf_balance, yf_cashflow = _yf_financials(ticker)

    def _show_yf_df(df, title):
        if df is None or (hasattr(df, 'empty') and df.empty): return
        try:
            df2 = df.T.copy() if hasattr(df, 'T') else pd.DataFrame(df).T
            df2.index = pd.to_datetime(df2.index).year.astype(str)
            df2 = df2.apply(pd.to_numeric, errors='coerce') / 1e6
            st.markdown(f"**{title}** *(values in $M — source: yfinance)*")
            st.dataframe(df2.style.format("${:,.1f}").background_gradient(
                cmap='RdYlGn', axis=1), use_container_width=True)
        except Exception as e:
            st.caption(f"Could not render {title}: {e}")

    def _show_fmp_df(rows: list, fields: list, labels: dict, title: str):
        if not rows: return
        df = _fmp_statements_to_df(rows, fields)
        if df.empty: return
        df.columns = [labels.get(c, c) for c in df.columns]
        st.markdown(f"**{title}** *(values in $M — source: FMP)*")
        st.dataframe(df.style.format("${:,.1f}", na_rep='—')
                      .background_gradient(cmap='RdYlGn', axis=0),
                     use_container_width=True)

    # Field maps for FMP
    INC_FIELDS = ['revenue','grossProfit','operatingIncome','ebitda',
                  'netIncome','eps','epsdiluted','weightedAverageShsOutDil']
    INC_LABELS = {'revenue':'Revenue','grossProfit':'Gross Profit',
                  'operatingIncome':'Op. Income','ebitda':'EBITDA',
                  'netIncome':'Net Income','eps':'EPS Basic',
                  'epsdiluted':'EPS Diluted','weightedAverageShsOutDil':'Diluted Shares'}

    BAL_FIELDS = ['totalCurrentAssets','totalNonCurrentAssets','totalAssets',
                  'totalCurrentLiabilities','totalNonCurrentLiabilities','totalLiabilities',
                  'totalStockholdersEquity','cashAndCashEquivalents','totalDebt','netDebt']
    BAL_LABELS = {'totalCurrentAssets':'Cur. Assets','totalNonCurrentAssets':'Non-Cur. Assets',
                  'totalAssets':'Total Assets','totalCurrentLiabilities':'Cur. Liab.',
                  'totalNonCurrentLiabilities':'Non-Cur. Liab.','totalLiabilities':'Total Liab.',
                  'totalStockholdersEquity':'Equity','cashAndCashEquivalents':'Cash',
                  'totalDebt':'Total Debt','netDebt':'Net Debt'}

    CF_FIELDS  = ['operatingCashFlow','capitalExpenditure','freeCashFlow',
                  'netCashUsedForInvestingActivities','netCashUsedProvidedByFinancingActivities',
                  'dividendsPaid','commonStockRepurchased','netChangeInCash']
    CF_LABELS  = {'operatingCashFlow':'Op. CF','capitalExpenditure':'CapEx',
                  'freeCashFlow':'Free CF','netCashUsedForInvestingActivities':'Investing CF',
                  'netCashUsedProvidedByFinancingActivities':'Financing CF',
                  'dividendsPaid':'Dividends','commonStockRepurchased':'Buybacks',
                  'netChangeInCash':'Net Change Cash'}

    KM_FIELDS  = ['revenuePerShare','netIncomePerShare','operatingCashFlowPerShare',
                  'freeCashFlowPerShare','bookValuePerShare','returnOnEquity',
                  'returnOnAssets','returnOnCapitalEmployed','debtToEquity',
                  'currentRatio','interestCoverage','peRatio','priceToBookRatio',
                  'evToEbitda','dividendYield']
    KM_LABELS  = {'revenuePerShare':'Rev/Share','netIncomePerShare':'EPS',
                  'operatingCashFlowPerShare':'OCF/Share','freeCashFlowPerShare':'FCF/Share',
                  'bookValuePerShare':'BVPS','returnOnEquity':'ROE',
                  'returnOnAssets':'ROA','returnOnCapitalEmployed':'ROCE',
                  'debtToEquity':'D/E','currentRatio':'Current',
                  'interestCoverage':'Int. Cover','peRatio':'P/E',
                  'priceToBookRatio':'P/B','evToEbitda':'EV/EBITDA',
                  'dividendYield':'Div Yield'}

    t1, t2, t3, t4 = st.tabs(["📊 Income", "🏦 Balance Sheet", "💰 Cash Flow", "📐 Key Metrics"])

    with t1:
        if fmp_inc:
            _show_fmp_df(fmp_inc, INC_FIELDS, INC_LABELS, "Income Statement")
            # Revenue + Net Income chart
            rev  = [r.get('revenue',  0) or 0 for r in reversed(fmp_inc)]
            ni   = [r.get('netIncome',0) or 0 for r in reversed(fmp_inc)]
            xlab = [r.get('date','')[:7] for r in reversed(fmp_inc)]
            if any(rev):
                fig_inc = go.Figure()
                fig_inc.add_trace(go.Bar(name='Revenue',    x=xlab, y=[v/1e9 for v in rev],
                                         marker_color=T['blue']))
                fig_inc.add_trace(go.Bar(name='Net Income', x=xlab, y=[v/1e9 for v in ni],
                                         marker_color=T['green']))
                fig_inc.update_layout(
                    barmode='group', title='Revenue vs Net Income ($B)',
                    paper_bgcolor=T['bg'], plot_bgcolor=T['panel'],
                    font=dict(color=T['white'], family='monospace'), height=320,
                    xaxis=dict(gridcolor=T['border']),
                    yaxis=dict(gridcolor=T['border'], title='$B'),
                    legend=dict(orientation='h'), margin=dict(l=10,r=10,t=45,b=10))
                st.plotly_chart(fig_inc, use_container_width=True)
        else:
            _show_yf_df(yf_income, "Income Statement")

    with t2:
        if fmp_bal:
            _show_fmp_df(fmp_bal, BAL_FIELDS, BAL_LABELS, "Balance Sheet")
            # Assets vs Liabilities vs Equity chart
            assets = [r.get('totalAssets',     0) or 0 for r in reversed(fmp_bal)]
            liabs  = [r.get('totalLiabilities',0) or 0 for r in reversed(fmp_bal)]
            equity = [r.get('totalStockholdersEquity',0) or 0 for r in reversed(fmp_bal)]
            xlab   = [r.get('date','')[:7] for r in reversed(fmp_bal)]
            if any(assets):
                fig_bal = go.Figure()
                fig_bal.add_trace(go.Bar(name='Total Assets',  x=xlab, y=[v/1e9 for v in assets],
                                         marker_color=T['blue']))
                fig_bal.add_trace(go.Bar(name='Total Liab.',   x=xlab, y=[v/1e9 for v in liabs],
                                         marker_color=T['red']))
                fig_bal.add_trace(go.Bar(name='Equity',        x=xlab, y=[v/1e9 for v in equity],
                                         marker_color=T['green']))
                fig_bal.update_layout(
                    barmode='group', title='Assets / Liabilities / Equity ($B)',
                    paper_bgcolor=T['bg'], plot_bgcolor=T['panel'],
                    font=dict(color=T['white'], family='monospace'), height=320,
                    xaxis=dict(gridcolor=T['border']),
                    yaxis=dict(gridcolor=T['border'], title='$B'),
                    legend=dict(orientation='h'), margin=dict(l=10,r=10,t=45,b=10))
                st.plotly_chart(fig_bal, use_container_width=True)
        else:
            _show_yf_df(yf_balance, "Balance Sheet")

    with t3:
        if fmp_cf:
            _show_fmp_df(fmp_cf, CF_FIELDS, CF_LABELS, "Cash Flow Statement")
            # Op CF vs Free CF chart
            ocf = [r.get('operatingCashFlow',0) or 0 for r in reversed(fmp_cf)]
            fcf = [r.get('freeCashFlow',     0) or 0 for r in reversed(fmp_cf)]
            xlab = [r.get('date','')[:7] for r in reversed(fmp_cf)]
            if any(ocf):
                fig_cf = go.Figure()
                fig_cf.add_trace(go.Bar(name='Op. Cash Flow', x=xlab, y=[v/1e9 for v in ocf],
                                        marker_color=T['amber']))
                fig_cf.add_trace(go.Bar(name='Free Cash Flow',x=xlab, y=[v/1e9 for v in fcf],
                                        marker_color=T['green']))
                fig_cf.update_layout(
                    barmode='group', title='Operating vs Free Cash Flow ($B)',
                    paper_bgcolor=T['bg'], plot_bgcolor=T['panel'],
                    font=dict(color=T['white'], family='monospace'), height=320,
                    xaxis=dict(gridcolor=T['border']),
                    yaxis=dict(gridcolor=T['border'], title='$B'),
                    legend=dict(orientation='h'), margin=dict(l=10,r=10,t=45,b=10))
                st.plotly_chart(fig_cf, use_container_width=True)
        else:
            _show_yf_df(yf_cashflow, "Cash Flow Statement")

    with t4:
        if fmp_km:
            _show_fmp_df(fmp_km, KM_FIELDS, KM_LABELS, "Key Metrics per Share & Ratios")
            # ROE / ROA trend
            roe  = [r.get('returnOnEquity', None) for r in reversed(fmp_km)]
            roa  = [r.get('returnOnAssets', None) for r in reversed(fmp_km)]
            xlab = [r.get('date','')[:7] for r in reversed(fmp_km)]
            roe_vals = [v * 100 if v is not None else None for v in roe]
            roa_vals = [v * 100 if v is not None else None for v in roa]
            if any(v is not None for v in roe_vals):
                fig_ret = go.Figure()
                fig_ret.add_trace(go.Scatter(name='ROE (%)', x=xlab, y=roe_vals,
                                             line=dict(color=T['amber'], width=2)))
                fig_ret.add_trace(go.Scatter(name='ROA (%)', x=xlab, y=roa_vals,
                                             line=dict(color=T['blue'], width=2)))
                fig_ret.add_hline(y=0, line_color=T['muted'], opacity=0.4)
                fig_ret.update_layout(
                    title='Return on Equity & Assets (%)',
                    paper_bgcolor=T['bg'], plot_bgcolor=T['panel'],
                    font=dict(color=T['white'], family='monospace'), height=300,
                    xaxis=dict(gridcolor=T['border']),
                    yaxis=dict(gridcolor=T['border'], title='%'),
                    legend=dict(orientation='h'), margin=dict(l=10,r=10,t=45,b=10))
                st.plotly_chart(fig_ret, use_container_width=True)
        else:
            if not fmp_key:
                st.info("💡 Add an **FMP API key** in Terminal → API Keys to unlock Key Metrics tab "
                        "(ROE, ROCE, FCF/share, D/E, P/E history — up to 10 years)")

    if not fmp_key:
        st.caption("💡 Add FMP API key for up to 10 years of data, quarterly toggle, "
                   "charts, and Key Metrics tab.")


def cmd_news(ticker: str, api_keys: dict):
    """TICKER NEWS — latest headlines for a specific stock.
    Priority: NewsAPI (searches company ticker) → Alpha Vantage → yfinance RSS.
    """
    newsapi_key = api_keys.get('newsapi_key', '').strip()
    av_key      = api_keys.get('alpha_vantage', '').strip()

    # Get company name for a richer NewsAPI search query
    info         = _yf_info(ticker)
    company_name = _safe_get(info, 'shortName', 'longName', default='')
    search_query = f'{ticker} {company_name}'.strip() if company_name else ticker

    st.markdown(f"<div class='term-header'>📰  {ticker.upper()} — NEWS</div>",
                unsafe_allow_html=True)

    all_items  = []
    used_na    = False

    # ── Primary: NewsAPI (/everything with ticker + company name) ──────────────
    if newsapi_key:
        na_articles = _fetch_newsapi(search_query, newsapi_key, page_size=20)
        if na_articles:
            used_na = True
            for a in na_articles:
                all_items.append({
                    'Source':   a.get('source', 'NewsAPI'),
                    'Date':     _fmt_newsapi_dt(a.get('publishedAt', '')),
                    'Headline': a.get('title', ''),
                    'Desc':     a.get('description', ''),
                    'Link':     a.get('url', ''),
                })

    # ── Secondary: Alpha Vantage sentiment ────────────────────────────────────
    if av_key:
        av_news = _fetch_av_news(ticker, av_key)
        for n in av_news:
            # Avoid duplicates by title prefix
            title = n.get('title', '')
            if not any(title[:40] == i['Headline'][:40] for i in all_items):
                all_items.append({
                    'Source':   n.get('source', 'Alpha Vantage'),
                    'Date':     n.get('time_published', '')[:16],
                    'Headline': title,
                    'Desc':     n.get('summary', '')[:160],
                    'Link':     n.get('url', ''),
                })

    # ── Fallback: yfinance RSS ────────────────────────────────────────────────
    yf_raw = _yf_news(ticker)
    for n in yf_raw:
        title = n.get('title', '')
        if not any(title[:40] == i['Headline'][:40] for i in all_items):
            ts = n.get('providerPublishTime', 0)
            dt = datetime.fromtimestamp(ts).strftime('%d %b %Y  %H:%M') if ts else '—'
            all_items.append({
                'Source':   n.get('publisher', 'yfinance'),
                'Date':     dt,
                'Headline': title,
                'Desc':     '',
                'Link':     n.get('link', ''),
            })

    if not all_items:
        st.info("No news available for this ticker at this time.")
        return

    if not newsapi_key:
        st.caption(
            "💡 Add a **NewsAPI key** (free at [newsapi.org](https://newsapi.org/register)) "
            "in Terminal → API Keys for richer, real-time ticker-specific news.")

    for item in all_items:
        link     = item.get('Link', '')
        desc     = item.get('Desc', '')
        link_tag = (f'  <a href="{link}" target="_blank" style="color:{T["blue"]}">↗</a>'
                    if link else '')
        desc_html = (
            f"<br><span style='color:{T['muted']};font-family:monospace;font-size:11px'>"
            f"{desc[:160]}{'…' if len(desc) > 160 else ''}</span>"
        ) if desc else ''
        st.markdown(
            f"<div class='term-panel' style='padding:8px 12px'>"
            f"<span class='term-lbl'>{item['Date']} &nbsp;|&nbsp; {item['Source']}</span><br>"
            f"<span style='color:{T['white']};font-family:monospace;font-size:13px'>"
            f"{item['Headline']}</span>{link_tag}{desc_html}"
            f"</div>", unsafe_allow_html=True)


def cmd_options(ticker: str, api_keys: dict):
    dates, calls, puts = _yf_options_chain(ticker)
    st.markdown(f"<div class='term-header'>⚙️  {ticker.upper()} — OPTIONS CHAIN (OPT)</div>",
                unsafe_allow_html=True)
    if not dates: st.error("No options data available."); return
    sel = st.selectbox("Expiry date", dates, key=f"opt_{ticker}")
    if sel != dates[0]:
        t = _yf_ticker(ticker)
        if t:
            chain = t.option_chain(sel)
            calls, puts = chain.calls, chain.puts
    col_keep = ['strike','lastPrice','bid','ask','volume','openInterest','impliedVolatility','inTheMoney']
    def _opt_df(df):
        if df is None or df.empty: return pd.DataFrame()
        cols = [c for c in col_keep if c in df.columns]
        out = df[cols].copy()
        if 'impliedVolatility' in out:
            out['impliedVolatility'] = (out['impliedVolatility']*100).round(1)
        return out
    ot1, ot2 = st.tabs(["📈 Calls", "📉 Puts"])
    with ot1:
        df_c = _opt_df(calls)
        if not df_c.empty:
            st.dataframe(df_c.style.background_gradient(
                subset=['impliedVolatility'] if 'impliedVolatility' in df_c.columns else [],
                cmap='YlOrRd'), use_container_width=True, hide_index=True)
    with ot2:
        df_p = _opt_df(puts)
        if not df_p.empty:
            st.dataframe(df_p.style.background_gradient(
                subset=['impliedVolatility'] if 'impliedVolatility' in df_p.columns else [],
                cmap='YlOrRd'), use_container_width=True, hide_index=True)
    # IV smile
    if calls is not None and not calls.empty and 'strike' in calls.columns and 'impliedVolatility' in calls.columns:
        info   = _yf_info(ticker)
        spot   = _safe_get(info,'currentPrice','regularMarketPrice', default=0)
        fig_iv = go.Figure()
        fig_iv.add_trace(go.Scatter(x=calls['strike'], y=calls['impliedVolatility']*100,
            name='Calls IV', line=dict(color=T['green'], width=2)))
        if puts is not None and not puts.empty:
            fig_iv.add_trace(go.Scatter(x=puts['strike'], y=puts['impliedVolatility']*100,
                name='Puts IV', line=dict(color=T['red'], width=2)))
        if spot:
            fig_iv.add_vline(x=spot, line_dash='dot', line_color=T['amber'],
                             annotation_text=f"Spot {spot:.2f}")
        fig_iv.update_layout(
            title='Implied Volatility Smile', xaxis_title='Strike', yaxis_title='IV (%)',
            paper_bgcolor=T['bg'], plot_bgcolor=T['panel'],
            font=dict(color=T['white']), height=350,
        )
        st.plotly_chart(fig_iv, use_container_width=True)


def cmd_dividends(ticker: str, api_keys: dict):
    div = _yf_dividends(ticker)
    st.markdown(f"<div class='term-header'>💵  {ticker.upper()} — DIVIDEND HISTORY (DVD)</div>",
                unsafe_allow_html=True)
    if div.empty: st.info("No dividend history found."); return
    if div.index.tz is not None:
        div.index = div.index.tz_localize(None)
    df = div.reset_index(); df.columns = ['Date','Dividend']
    df['Date'] = pd.to_datetime(df['Date'])
    annual = df.groupby(df['Date'].dt.year)['Dividend'].sum().reset_index()
    annual.columns = ['Year','Annual Dividend']
    c1, c2 = st.columns(2)
    with c1:
        fig_div = go.Figure(go.Bar(
            x=annual['Year'].astype(str), y=annual['Annual Dividend'],
            marker_color=T['amber'], text=annual['Annual Dividend'].apply(lambda x: f"${x:.3f}"),
            textposition='outside',
        ))
        fig_div.update_layout(
            title='Annual Dividend per Share', paper_bgcolor=T['bg'], plot_bgcolor=T['panel'],
            font=dict(color=T['white']), height=300, xaxis_title='Year', yaxis_title='Dividend ($)',
        )
        st.plotly_chart(fig_div, use_container_width=True)
    with c2:
        st.dataframe(df.tail(20).sort_values('Date',ascending=False)
                       .style.format({'Dividend':'${:.4f}'}),
                     use_container_width=True, hide_index=True)


def cmd_compare(tickers: list, api_keys: dict):
    st.markdown(f"<div class='term-header'>⚖️  COMPARE — {' vs '.join(tkr.upper() for tkr in tickers)}</div>",
                unsafe_allow_html=True)
    period = st.select_slider("Period", ['1mo','3mo','6mo','1y','2y','5y'], value='1y',
                               key='comp_period')
    fig = go.Figure()
    COLORS = [T['amber'],T['green'],T['blue'],T['red'],'#ce93d8','#80cbc4']
    stats_rows = []
    for i, tkr in enumerate(tickers):
        df = _yf_history(tkr, period=period)
        if df.empty: st.warning(f"No data for {tkr}"); continue
        norm = 100 * df['Close'] / df['Close'].iloc[0]
        fig.add_trace(go.Scatter(x=df.index, y=norm, name=tkr.upper(),
                                 line=dict(color=COLORS[i%len(COLORS)], width=2)))
        ret_tot = (df['Close'].iloc[-1]/df['Close'].iloc[0]-1)*100
        ann_vol = df['Close'].pct_change().std() * np.sqrt(252) * 100
        stats_rows.append({'Ticker': tkr.upper(), 'Total Return (%)': f"{ret_tot:+.2f}%",
                           'Ann. Volatility (%)': f"{ann_vol:.2f}%",
                           'Sharpe (est.)': f"{(ret_tot/100)/(ann_vol/100):.2f}" if ann_vol else '—'})
    fig.add_hline(y=100, line_dash='dot', line_color=T['muted'], opacity=0.6)
    fig.update_layout(
        title='Normalised Comparison (Base = 100)', xaxis_title='Date', yaxis_title='Indexed Value',
        paper_bgcolor=T['bg'], plot_bgcolor=T['panel'], font=dict(color=T['white']),
        height=480, hovermode='x unified',
        legend=dict(orientation='h', y=1.08),
    )
    st.plotly_chart(fig, use_container_width=True)
    if stats_rows:
        st.dataframe(pd.DataFrame(stats_rows), use_container_width=True, hide_index=True)


def cmd_wei(api_keys: dict):
    st.markdown(f"<div class='term-header'>🌍  WEI — WORLD EQUITY INDICES</div>",
                unsafe_allow_html=True)
    rows = []
    syms = [sym for _, sym in WORLD_INDICES]
    closes_by_sym = {}
    try:
        # period='2d' is not enough: every index sits on a different exchange
        # calendar, so a 2-day union window leaves only ONE valid close per
        # symbol and the len(closes) >= 2 test below can never pass. Use 5d so
        # each symbol has at least two real closes.
        data = yf.download(syms, period='5d', interval='1d', progress=False, auto_adjust=True)
        for _, sym in WORLD_INDICES:
            try:
                closes = data['Close'][sym].dropna()
                if len(closes) >= 2:
                    closes_by_sym[sym] = closes
            except Exception:
                pass
    except Exception:
        pass
    # Backfill whatever the batch missed. yf.download regularly returns a partial
    # frame for a 14-symbol multi-exchange request, so an all-or-nothing
    # `if not rows:` fallback silently drops whole regions from the board.
    for name, sym in WORLD_INDICES:
        closes = closes_by_sym.get(sym)
        if closes is None:
            df = _yf_history(sym, period='5d')
            closes = df['Close'].dropna() if not df.empty else None
        if closes is None or len(closes) < 2:
            continue
        # Compare against the previous session on that exchange's own calendar,
        # not simply the previous row: a dropped daily bar would otherwise make
        # the change span two sessions (see _last_two_sessions).
        last, prev, d_last = _last_two_sessions(sym, closes)
        if not prev:
            continue
        chg = last - prev
        rows.append({'Index': name, 'Symbol': sym, 'Last': f"{last:,.2f}",
                     'Prev': prev, 'Date': d_last,
                     'Chg': chg, 'Chg%': chg / prev * 100})
    # Keep the board in WORLD_INDICES order whichever path supplied each row.
    _order = {sym: i for i, (_, sym) in enumerate(WORLD_INDICES)}
    rows.sort(key=lambda r: _order.get(r['Symbol'], 99))
    if not rows: st.error("Could not fetch index data."); return

    # ── Attach matching index futures + implied cash open ────────────────────
    session = _us_session()
    for r in rows:
        meta = INDEX_FUTURES.get(r['Symbol'])
        if not meta: continue
        fut_lbl, fut_sym = meta
        f_last, f_chg_p = _futures_since_cash_close(fut_sym, r['Date'])
        try:
            cash_last = float(r['Last'].replace(',', ''))
        except ValueError:
            continue
        if f_last is None or f_chg_p is None:
            # No intraday futures: fall back to the daily change, but apply it to
            # the *previous* cash close so the move is not counted twice.
            f_last, f_prev = _yf_last_prev(fut_sym)
            if f_last is None or not f_prev: continue
            f_chg_p = (f_last - f_prev) / f_prev * 100
            r['ImpliedOpen'] = r['Prev'] * (1 + f_chg_p / 100)
        else:
            r['ImpliedOpen'] = cash_last * (1 + f_chg_p / 100)
        r['Fut']         = fut_lbl
        r['FutLast']     = f_last
        r['FutChg%']     = f_chg_p

    c1, c2, c3, c4 = st.columns(4)
    for i, r in enumerate(rows):
        col = [c1,c2,c3,c4][i%4]
        arrow = '▲' if r['Chg'] >= 0 else '▼'
        color = T['green'] if r['Chg'] >= 0 else T['red']
        fut_html = ''
        if 'Fut' in r:
            f_arrow = '▲' if r['FutChg%'] >= 0 else '▼'
            f_color = T['green'] if r['FutChg%'] >= 0 else T['red']
            badge = ''
            if session == 'PRE':
                badge = (f"<span style='background:{T['header']};color:{T['amber']};"
                         f"font-family:monospace;font-size:9px;padding:1px 5px;"
                         f"border-radius:3px;margin-left:5px'>🌅 PRE-MKT</span>")
            elif session == 'AH':
                badge = (f"<span style='background:{T['header']};color:{T['blue']};"
                         f"font-family:monospace;font-size:9px;padding:1px 5px;"
                         f"border-radius:3px;margin-left:5px'>🌙 AFT-HRS</span>")
            fut_html = (
                f"<div style='border-top:1px solid {T['border']};margin-top:6px;padding-top:5px'>"
                f"<div style='font-family:monospace;font-size:10px;color:{T['muted']}'>"
                f"{r['Fut']} fut {f_arrow}<span style='color:{f_color}'>{r['FutChg%']:+.2f}%</span>"
                f"{badge}</div>"
                f"<div style='font-family:monospace;font-size:10px;color:{T['muted']}'>"
                f"Impl. open <span style='color:{T['white']}'>{r['ImpliedOpen']:,.2f}</span></div>"
                f"</div>"
            )
        col.markdown(
            f"<div class='term-panel' style='padding:8px;text-align:center'>"
            f"<div style='color:{T['amber']};font-family:monospace;font-weight:bold;font-size:11px'>{r['Index']}</div>"
            f"<div style='color:{T['white']};font-family:monospace;font-size:14px'>{r['Last']}</div>"
            f"<div style='color:{color};font-family:monospace;font-size:12px'>{arrow} {r['Chg%']:+.2f}%</div>"
            f"{fut_html}"
            f"</div>", unsafe_allow_html=True)
    st.caption("Day change = latest session vs the previous session on that exchange's own calendar. "
               "Futures = ES/NQ/YM/RTY, measured from the 16:00 ET cash close, so "
               "implied open = cash close × (1 + post-close futures move). "
               "PRE-MKT shown when the US cash market has not opened yet.")
    # Heat map
    if rows:
        labels = [r['Index'] for r in rows]
        chg_pct = [r['Chg%'] for r in rows]
        bar_colors = [T['green'] if v >= 0 else T['red'] for v in chg_pct]
        fig = go.Figure(go.Bar(
            x=labels, y=chg_pct, marker_color=bar_colors,
            text=[f"{v:+.2f}%" for v in chg_pct], textposition='outside',
        ))
        fig.add_hline(y=0, line_color=T['muted'], opacity=0.5)
        fig.update_layout(
            title='World Index Performance (%)', paper_bgcolor=T['bg'], plot_bgcolor=T['panel'],
            font=dict(color=T['white'], family='monospace'), height=380, xaxis_tickangle=-30,
            margin=dict(b=80),
        )
        st.plotly_chart(fig, use_container_width=True)


def cmd_movers(category: str, api_keys: dict):
    cat_map = {'g': 'gainers', 'l': 'losers', 'a': 'active',
               'gainers': 'gainers', 'losers': 'losers', 'active': 'active'}
    cat = cat_map.get(category.lower(), 'gainers')
    st.markdown(f"<div class='term-header'>🚀  MOVERS — {cat.upper()}</div>", unsafe_allow_html=True)
    # Use yfinance screener approach
    screener_map = {
        'gainers': 'day_gainers', 'losers': 'day_losers', 'active': 'most_actives'
    }
    try:
        from yfinance import Screener
        screen = Screener()
        screen.set_predefined_body(screener_map[cat])
        quotes = screen.response.get('quotes', [])[:20]
        if quotes:
            rows = []
            for q in quotes:
                rows.append({
                    'Symbol':       q.get('symbol',''),
                    'Name':         q.get('shortName','')[:30],
                    'Price':        f"${q.get('regularMarketPrice',0):,.2f}",
                    'Change':       f"{q.get('regularMarketChange',0):+.2f}",
                    'Change%':      f"{q.get('regularMarketChangePercent',0):+.2f}%",
                    'Volume':       f"{q.get('regularMarketVolume',0):,.0f}",
                    'Market Cap':   _fmt_large(q.get('marketCap')),
                })
            df_m = pd.DataFrame(rows)
            st.dataframe(df_m, use_container_width=True, hide_index=True)
            return
    except: pass
    # Fallback: hardcoded watchlist
    if cat == 'gainers':
        fallback = ['NVDA','TSLA','AAPL','MSFT','AMZN','GOOG','META','NFLX','AMD','SHOP']
    elif cat == 'losers':
        fallback = ['XOM','CVX','JPM','BAC','WFC','GS','C','MS','PFE','JNJ']
    else:
        fallback = ['SPY','QQQ','AAPL','TSLA','NVDA','AMZN','MSFT','GOOG','AMD','META']
    rows = []
    for sym in fallback:
        df = _yf_history(sym, period='2d')
        if df.empty or len(df) < 2: continue
        prev, last = float(df['Close'].iloc[-2]), float(df['Close'].iloc[-1])
        chg = last-prev; chg_p = chg/prev*100
        rows.append({'Symbol': sym, 'Price': f"${last:,.2f}",
                     'Change': f"{chg:+.2f}", 'Change%': f"{chg_p:+.2f}%"})
    rows.sort(key=lambda x: float(x['Change%'].replace('%','')), reverse=(cat!='losers'))
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.warning("Screener data unavailable. Check your network connection.")


def cmd_fx(api_keys: dict):
    st.markdown(f"<div class='term-header'>💱  FX — FOREX MONITOR</div>", unsafe_allow_html=True)
    rows = []
    for name, sym in FX_PAIRS:
        df = _yf_history(sym, period='5d')
        if df.empty or len(df) < 2: continue
        prev, last = float(df['Close'].iloc[-2]), float(df['Close'].iloc[-1])
        chg_p = (last - prev) / prev * 100
        rows.append({'Pair': name, 'Rate': f"{last:.5f}",
                     'Chg': last-prev, 'Chg%': chg_p,
                     'W%': (last/float(df['Close'].iloc[0])-1)*100})
    if not rows: st.error("No FX data available."); return
    c1, c2, c3, c4 = st.columns(4)
    for i, r in enumerate(rows):
        col = [c1,c2,c3,c4][i%4]
        color = T['green'] if r['Chg'] >= 0 else T['red']
        arrow = '▲' if r['Chg'] >= 0 else '▼'
        col.markdown(
            f"<div class='term-panel' style='padding:8px;text-align:center'>"
            f"<div style='color:{T['amber']};font-family:monospace;font-weight:bold;font-size:11px'>{r['Pair']}</div>"
            f"<div style='color:{T['white']};font-family:monospace;font-size:15px'>{r['Rate']}</div>"
            f"<div style='color:{color};font-family:monospace;font-size:12px'>{arrow} {r['Chg%']:+.3f}%</div>"
            f"</div>", unsafe_allow_html=True)
    # Bar chart
    fig = _bar_chart_term([r['Pair'] for r in rows], [r['Chg%'] for r in rows],
                          'Forex Daily Change (%)')
    st.plotly_chart(fig, use_container_width=True)
    # 3-month chart of selected pair
    sel = st.selectbox("View chart for pair", [r['Pair'] for r in rows], key='fx_sel')
    sym = dict(FX_PAIRS).get(sel, '')
    if sym:
        df = _yf_history(sym, period='3mo')
        if not df.empty:
            fig2 = _line_chart_term(df.index, df['Close'], f"{sel} — 3 Month", sel, T['amber'])
            st.plotly_chart(fig2, use_container_width=True)


def cmd_crypto(api_keys: dict):
    st.markdown(f"<div class='term-header'>₿  CRYPTO — DIGITAL ASSETS DASHBOARD</div>",
                unsafe_allow_html=True)
    rows = []
    for name, sym in CRYPTO_PAIRS:
        df = _yf_history(sym, period='5d')
        if df.empty or len(df) < 2: continue
        prev, last = float(df['Close'].iloc[-2]), float(df['Close'].iloc[-1])
        wk_start = float(df['Close'].iloc[0])
        chg_p = (last-prev)/prev*100
        wk_p  = (last-wk_start)/wk_start*100
        rows.append({'Name': name, 'Symbol': sym.replace('-USD',''),
                     'Price ($)': f"{last:,.4f}" if last < 1 else f"{last:,.2f}",
                     'Chg': last-prev, 'Chg%': chg_p, 'W%': wk_p})
    if not rows: st.error("No crypto data available."); return
    c1,c2,c3,c4,c5 = st.columns(5)
    for i, r in enumerate(rows):
        col = [c1,c2,c3,c4,c5][i%5]
        color = T['green'] if r['Chg'] >= 0 else T['red']
        arrow = '▲' if r['Chg'] >= 0 else '▼'
        col.markdown(
            f"<div class='term-panel' style='padding:8px;text-align:center'>"
            f"<div style='color:{T['amber']};font-family:monospace;font-weight:bold;font-size:12px'>{r['Symbol']}</div>"
            f"<div style='color:{T['white']};font-family:monospace;font-size:13px'>${r['Price ($)']}</div>"
            f"<div style='color:{color};font-family:monospace;font-size:11px'>{arrow} {r['Chg%']:+.2f}%</div>"
            f"</div>", unsafe_allow_html=True)
    # Bar
    st.plotly_chart(_bar_chart_term(
        [r['Name'] for r in rows], [r['Chg%'] for r in rows],
        'Crypto Daily Change (%)'), use_container_width=True)
    # BTC 1Y chart
    df_btc = _yf_history('BTC-USD', period='1y')
    if not df_btc.empty:
        st.plotly_chart(_candlestick_chart(df_btc, 'Bitcoin (BTC-USD) — 1 Year', height=400),
                        use_container_width=True)


def cmd_coin(coin_name: str):
    """COIN <name> — single-coin deep dive via CoinGecko."""
    import requests as _req
    q = coin_name.lower().strip()
    coin_id = COIN_MAP.get(q, q)

    try:
        r = _req.get(
            f'https://api.coingecko.com/api/v3/coins/{coin_id}',
            params={'localization': 'false', 'tickers': 'false',
                    'community_data': 'false', 'developer_data': 'false'},
            timeout=8,
        )
        r.raise_for_status()
        d = r.json()
    except Exception:
        st.error(f"Coin '{coin_name}' not found on CoinGecko. Try COIN TOP for the top 10.")
        return

    md = d.get('market_data', {})
    name = d.get('name', coin_name.title())
    sym = d.get('symbol', '').upper()
    price = md.get('current_price', {}).get('usd')
    mc = md.get('market_cap', {}).get('usd')
    vol = md.get('total_volume', {}).get('usd')
    chg_24h = md.get('price_change_percentage_24h')
    chg_7d = md.get('price_change_percentage_7d')
    chg_30d = md.get('price_change_percentage_30d')
    high_24 = md.get('high_24h', {}).get('usd')
    low_24 = md.get('low_24h', {}).get('usd')
    circ = md.get('circulating_supply')
    total_s = md.get('total_supply')
    ath = md.get('ath', {}).get('usd')
    ath_date = (md.get('ath_date', {}).get('usd', '') or '')[:10]
    rank = d.get('market_cap_rank', '—')

    st.markdown(f"<div class='term-header'>₿  {name} ({sym}) — COIN DEEP DIVE</div>",
                unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns(4)
    color_24 = T['green'] if chg_24h and chg_24h >= 0 else T['red']
    color_7d = T['green'] if chg_7d and chg_7d >= 0 else T['red']
    arrow_24 = '▲' if chg_24h and chg_24h >= 0 else '▼'
    arrow_7d = '▲' if chg_7d and chg_7d >= 0 else '▼'
    c1.markdown(f"<div class='term-panel' style='text-align:center'><span class='term-lbl'>Price</span><br>"
                f"<span class='term-val'>${price:,.4f}</span></div>" if price and price < 1
                else f"<div class='term-panel' style='text-align:center'><span class='term-lbl'>Price</span><br>"
                f"<span class='term-val'>${price:,.2f}</span></div>", unsafe_allow_html=True)
    c2.markdown(f"<div class='term-panel' style='text-align:center'><span class='term-lbl'>Market Cap</span><br>"
                f"<span class='term-val'>${mc:,.0f}</span></div>" if mc
                else "", unsafe_allow_html=True)
    c3.markdown(f"<div class='term-panel' style='text-align:center'>"
                f"<span class='term-lbl'>24h</span><br>"
                f"<span style='color:{color_24};font-family:monospace;font-size:14px;font-weight:bold'>"
                f"{arrow_24} {chg_24h:+.2f}%</span></div>", unsafe_allow_html=True)
    c4.markdown(f"<div class='term-panel' style='text-align:center'>"
                f"<span class='term-lbl'>7d</span><br>"
                f"<span style='color:{color_7d};font-family:monospace;font-size:14px;font-weight:bold'>"
                f"{arrow_7d} {chg_7d:+.2f}%</span></div>", unsafe_allow_html=True)

    cols = st.columns(3)
    rank_display = f"#{rank}" if rank != '—' else '—'
    cols[0].metric("Market Cap Rank", rank_display)
    cols[0].metric("24h High", f"${high_24:,.4f}" if high_24 and high_24 < 1 else f"${high_24:,.2f}" if high_24 else '—')
    cols[0].metric("24h Low", f"${low_24:,.4f}" if low_24 and low_24 < 1 else f"${low_24:,.2f}" if low_24 else '—')
    cols[1].metric("Volume (24h)", f"${vol:,.0f}" if vol else '—')
    cols[1].metric("30d Change", f"{chg_30d:+.2f}%" if chg_30d else '—')
    cols[1].metric("Circulating Supply", f"{circ:,.0f}" if circ else '—')
    cols[2].metric("All-Time High", f"${ath:,.2f}" if ath else '—')
    cols[2].metric("ATH Date", ath_date if ath_date else '—')
    cols[2].metric("Total Supply", f"{total_s:,.0f}" if total_s else '—')

    # Price chart via yfinance
    yf_sym = f"{sym}-USD" if sym else 'BTC-USD'
    df = _yf_history(yf_sym, period='1y')
    if not df.empty:
        st.plotly_chart(_candlestick_chart(df, f'{name} ({yf_sym}) — 1 Year', height=400),
                        use_container_width=True)


def cmd_crypto_top(api_keys: dict):
    """CRYPTO TOP — top 10 cryptos by market cap via CoinGecko."""
    import requests as _req
    st.markdown(f"<div class='term-header'>🏆  CRYPTO TOP 10 — BY MARKET CAP</div>",
                unsafe_allow_html=True)
    try:
        r = _req.get('https://api.coingecko.com/api/v3/coins/markets',
                     params={'vs_currency': 'usd', 'order': 'market_cap_desc',
                             'per_page': 10, 'page': 1, 'sparkline': 'false'},
                     timeout=8)
        r.raise_for_status()
        coins = r.json()
    except Exception:
        st.error("Could not fetch crypto top 10 from CoinGecko.")
        return

    rows = []
    for c in coins:
        name = c.get('name', '')
        sym = c.get('symbol', '').upper()
        price = c.get('current_price')
        mc = c.get('market_cap', 0)
        vol = c.get('total_volume', 0)
        chg = c.get('price_change_percentage_24h')
        rows.append({
            'Name': name, 'Symbol': sym, 'Price': price,
            'Market Cap': mc, 'Volume 24h': vol, '24h%': chg,
        })

    # Card grid
    cols = st.columns(5)
    for i, r in enumerate(rows[:10]):
        col = cols[i % 5]
        color = T['green'] if r['24h%'] and r['24h%'] >= 0 else T['red']
        arrow = '▲' if r['24h%'] and r['24h%'] >= 0 else '▼'
        chg_s = f"{r['24h%']:+.2f}%" if r['24h%'] else '—'
        price_s = f"${r['Price']:,.4f}" if r['Price'] and r['Price'] < 1 else f"${r['Price']:,.2f}" if r['Price'] else '—'
        col.markdown(
            f"<div class='term-panel' style='padding:8px;text-align:center'>"
            f"<div style='color:{T['amber']};font-family:monospace;font-weight:bold;font-size:11px'>"
            f"#{i+1} {r['Symbol']}</div>"
            f"<div style='color:{T['white']};font-family:monospace;font-size:12px'>{price_s}</div>"
            f"<div style='color:{color};font-family:monospace;font-size:10px'>{arrow} {chg_s}</div>"
            f"</div>", unsafe_allow_html=True)

    # Table
    df = pd.DataFrame(rows)
    for c in ['Market Cap', 'Volume 24h']:
        if c in df.columns:
            df[c] = df[c].apply(lambda x: f"${x:,.0f}" if pd.notna(x) else '—')
    if '24h%' in df.columns:
        df['24h%'] = df['24h%'].apply(lambda x: f"{x:+.2f}%" if pd.notna(x) else '—')
    if 'Price' in df.columns:
        df['Price'] = df['Price'].apply(
            lambda x: f"${x:,.4f}" if pd.notna(x) and x < 1 else
                      f"${x:,.2f}" if pd.notna(x) else '—')
    st.dataframe(df, use_container_width=True, hide_index=True)

    # Bar chart
    fig = go.Figure(go.Bar(
        x=[r['Symbol'] for r in rows],
        y=[r['24h%'] if r['24h%'] else 0 for r in rows],
        marker_color=[T['green'] if r['24h%'] and r['24h%'] >= 0 else T['red'] for r in rows],
    ))
    fig.update_layout(
        title='Top 10 Crypto — 24h Change (%)',
        paper_bgcolor=T['bg'], plot_bgcolor=T['panel'],
        font=dict(color=T['white'], family='monospace'),
        height=350,
        xaxis=dict(gridcolor='#1e3a5f'),
        yaxis=dict(gridcolor='#1e3a5f'),
    )
    st.plotly_chart(fig, use_container_width=True)


def cmd_news_feed(api_keys: dict):
    """NEWS FEED — aggregated news from 13+ RSS feeds."""
    from chat import FINANCIAL_RSS_FEEDS, _news_rss
    st.markdown(f"<div class='term-header'>📰  NEWS FEED — AGGREGATED RSS</div>",
                unsafe_allow_html=True)
    result = _news_rss('')
    articles = result.get('articles', [])
    if not articles:
        st.info("No RSS articles available. Try again later.")
        return
    st.caption(f"📡 {result['article_count']} articles from {len(FINANCIAL_RSS_FEEDS)} RSS feeds")
    for art in articles:
        src = art.get('source', '')
        title = art.get('title', '')
        date = art.get('date', '')
        snippet = art.get('snippet', '')
        link = art.get('url', '')
        src_badge = f"<span style='color:{T['blue']};font-family:monospace;font-size:10px'>[{src}]</span>"
        date_badge = f"<span style='color:{T['muted']};font-family:monospace;font-size:10px'>{date}</span>" if date else ''
        link_html = f" <a href='{link}' target='_blank' style='color:{T['blue']};font-size:10px'>🔗</a>" if link else ''
        st.markdown(
            f"<div class='term-panel' style='padding:10px'>"
            f"<div style='font-family:monospace;font-size:13px;color:{T['white']}'>"
            f"{src_badge} {title}{link_html}</div>"
            f"<div style='margin-top:2px'>{date_badge}"
            f"<span style='color:{T['muted']};font-family:monospace;font-size:11px'> {snippet}</span>"
            f"</div></div>", unsafe_allow_html=True)


def cmd_news_sentiment(query: str):
    """NEWS SENTIMENT — news with GDELT tone/sentiment scoring."""
    from chat import _news_gdelt
    st.markdown(f"<div class='term-header'>📊  NEWS SENTIMENT — {query.upper()}</div>",
                unsafe_allow_html=True)
    try:
        result = _news_gdelt(query)
    except Exception:
        st.error("News sentiment unavailable (GDELT & yfinance both failed).")
        return
    articles = result.get('articles', [])
    if not articles:
        st.info("No GDELT articles available.")
        return
    for art in articles:
        title = art.get('title', '')
        src = art.get('source', '')
        snippet = art.get('snippet', '')
        link = art.get('url', '')
        tone = 0.0
        import re as _re_tone
        tone_match = _re_tone.search(r'Tone[=:]?\s*([-.\d]+)', snippet or '')
        if tone_match:
            tone = float(tone_match.group(1))
        if tone > 2:
            badge = f"<span style='color:{T['green']};font-weight:bold'>▲ BULLISH</span>"
            badge_color = T['green']
        elif tone < -2:
            badge = f"<span style='color:{T['red']};font-weight:bold'>▼ BEARISH</span>"
            badge_color = T['red']
        else:
            badge = f"<span style='color:{T['muted']}'>● NEUTRAL</span>"
            badge_color = T['muted']
        tone_pct = f"<span style='color:{badge_color};font-family:monospace;font-size:10px'>tone: {tone:+.1f}</span>"
        link_html = f" <a href='{link}' target='_blank' style='color:{T['blue']};font-size:10px'>🔗</a>" if link else ''
        st.markdown(
            f"<div class='term-panel' style='padding:10px'>"
            f"<div style='font-family:monospace;font-size:13px;color:{T['white']}'>"
            f"{badge} {title}{link_html}</div>"
            f"<div style='margin-top:2px'>"
            f"<span style='color:{T['blue']};font-size:10px'>[{src}]</span> "
            f"{tone_pct}"
            f"</div></div>", unsafe_allow_html=True)


def cmd_sentiment(ticker: str):
    """SENTIMENT <ticker> — news sentiment analysis for a stock."""
    from chat import _news_gdelt
    st.markdown(f"<div class='term-header'>📊  SENTIMENT — {ticker.upper()}</div>",
                unsafe_allow_html=True)

    # Fetch GDELT news with tone
    result = _news_gdelt(ticker)
    articles = result.get('articles', [])
    if not articles:
        st.info(f"No sentiment data for {ticker}.")
        return

    import re as _re_st
    tones = []
    for art in articles:
        snippet = art.get('snippet', '')
        tone_match = _re_st.search(r'Tone[=:]?\s*([-.\d]+)', snippet or '')
        if tone_match:
            tones.append(float(tone_match.group(1)))

    avg_tone = sum(tones) / len(tones) if tones else 0

    # Summary card
    c1, c2, c3 = st.columns(3)
    sentiment_label = "Bullish" if avg_tone > 2 else ("Bearish" if avg_tone < -2 else "Neutral")
    sentiment_color = T['green'] if avg_tone > 2 else (T['red'] if avg_tone < -2 else T['muted'])
    c1.markdown(f"<div class='term-panel' style='text-align:center'>"
                f"<span class='term-lbl'>Overall Sentiment</span><br>"
                f"<span style='color:{sentiment_color};font-family:monospace;font-size:18px;font-weight:bold'>"
                f"{sentiment_label}</span></div>", unsafe_allow_html=True)
    c2.markdown(f"<div class='term-panel' style='text-align:center'>"
                f"<span class='term-lbl'>Avg Tone Score</span><br>"
                f"<span class='term-val'>{avg_tone:+.2f}</span></div>", unsafe_allow_html=True)
    c3.markdown(f"<div class='term-panel' style='text-align:center'>"
                f"<span class='term-lbl'>Articles Analyzed</span><br>"
                f"<span class='term-val'>{len(tones)}</span></div>", unsafe_allow_html=True)

    # Sentiment distribution bar
    bullish = sum(1 for t in tones if t > 2)
    neutral = sum(1 for t in tones if -2 <= t <= 2)
    bearish = sum(1 for t in tones if t < -2)
    fig = go.Figure(go.Bar(
        x=['Bullish', 'Neutral', 'Bearish'],
        y=[bullish, neutral, bearish],
        marker_color=[T['green'], T['muted'], T['red']],
        text=[bullish, neutral, bearish],
        textposition='auto',
    ))
    fig.update_layout(
        title=f'Sentiment Distribution — {ticker.upper()}',
        paper_bgcolor=T['bg'], plot_bgcolor=T['panel'],
        font=dict(color=T['white'], family='monospace'),
        height=300,
        xaxis=dict(gridcolor='#1e3a5f'),
        yaxis=dict(gridcolor='#1e3a5f'),
    )
    st.plotly_chart(fig, use_container_width=True)

    # Articles
    st.markdown(f"<div class='term-lbl'>Latest articles with tone:</div>", unsafe_allow_html=True)
    for art in articles[:8]:
        title = art.get('title', '')
        src = art.get('source', '')
        snippet = art.get('snippet', '')
        link = art.get('url', '')
        # Find tone in snippet
        tone = 0
        tone_match = _re_st.search(r'Tone[=:]?\s*([-.\d]+)', snippet or '')
        if tone_match:
            tone = float(tone_match.group(1))
        tone_color = T['green'] if tone > 2 else (T['red'] if tone < -2 else T['muted'])
        tone_dot = '▲' if tone > 2 else ('▼' if tone < -2 else '●')
        link_html = f" <a href='{link}' target='_blank' style='color:{T['blue']};font-size:10px'>🔗</a>" if link else ''
        st.markdown(
            f"<div class='term-panel' style='padding:8px'>"
            f"<span style='color:{tone_color};font-weight:bold'>{tone_dot} {tone:+.1f}</span> "
            f"<span style='color:{T['white']};font-family:monospace;font-size:12px'>{title}</span>{link_html}"
            f"<br><span style='color:{T['blue']};font-size:10px'>[{src}]</span>"
            f"</div>", unsafe_allow_html=True)


def cmd_econ_global(api_keys: dict):
    """ECON GLOBAL — compare macro indicators across US, EU, China, Japan via World Bank."""
    import requests as _req
    st.markdown(f"<div class='term-header'>🌍  ECON GLOBAL — WORLD BANK MACRO</div>",
                unsafe_allow_html=True)

    INDICATORS = [
        ('GDP Growth (%)', 'NY.GDP.MKTP.KD.ZG', '%'),
        ('GDP per Cap ($)', 'NY.GDP.PCAP.CD', '$'),
        ('Inflation (CPI %)', 'FP.CPI.TOTL.ZG', '%'),
        ('Unemployment (%)', 'SL.UEM.TOTL.ZS', '%'),
        ('Population', 'SP.POP.TOTL', ''),
        ('Exports (% of GDP)', 'NE.EXP.GNFS.ZS', '%'),
        ('Imports (% of GDP)', 'NE.IMP.GNFS.ZS', '%'),
    ]
    COUNTRIES = ['US', 'EU', 'CN', 'JP', 'GB', 'DE', 'FR', 'IN', 'BR', 'KR']

    rows = []
    for ind_name, ind_code, unit in INDICATORS:
        row = {'Indicator': ind_name}
        for c in COUNTRIES:
            try:
                url = f'http://api.worldbank.org/v2/country/{c}/indicator/{ind_code}'
                r = _req.get(url, params={'format': 'json', 'per_page': 3, 'date': '2020:2030'},
                             timeout=8)
                data = r.json()
                if data and len(data) > 1:
                    obs = [o for o in data[1] if o.get('value') is not None]
                    if obs:
                        val = float(obs[0]['value'])
                        if unit == '$':
                            row[c] = f"${val:,.0f}"
                        elif unit == '%':
                            row[c] = f"{val:.1f}%"
                        else:
                            row[c] = f"{val:,.0f}"
                    else:
                        row[c] = '—'
                else:
                    row[c] = '—'
            except Exception:
                row[c] = '—'
        rows.append(row)

    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.caption("🌐 Source: World Bank API (free, no key needed). Data may be delayed by 1-2 years.")
    # GDP growth comparison bar
    try:
        gdp_row = next(r for r in rows if r['Indicator'] == 'GDP Growth (%)')
        gdp_data = [(c, gdp_row[c]) for c in COUNTRIES if gdp_row[c] != '—']
        if gdp_data:
            labels_g, vals_g = zip(*[(x[0], float(x[1].replace('%', ''))) for x in gdp_data])
            fig = go.Figure(go.Bar(
                x=list(labels_g), y=list(vals_g),
                marker_color=[T['green'] if v >= 0 else T['red'] for v in vals_g],
                text=[f"{v:.1f}%" for v in vals_g],
                textposition='auto',
            ))
            fig.update_layout(
                title='GDP Growth (%) by Country',
                paper_bgcolor=T['bg'], plot_bgcolor=T['panel'],
                font=dict(color=T['white'], family='monospace'),
                height=350,
                xaxis=dict(gridcolor='#1e3a5f'),
                yaxis=dict(gridcolor='#1e3a5f'),
            )
            st.plotly_chart(fig, use_container_width=True)
    except (StopIteration, ValueError):
        pass


def cmd_rates(api_keys: dict):
    st.markdown(f"<div class='term-header'>📐  RATES — US YIELD CURVE</div>", unsafe_allow_html=True)
    fred_key = api_keys.get('fred','')
    # US Treasuries via yfinance
    yf_map = {'3M':'^IRX','5Y':'^FVX','10Y':'^TNX','30Y':'^TYX'}
    fred_map = {'1M':'DGS1MO','6M':'DGS6MO','1Y':'DGS1','2Y':'DGS2','7Y':'DGS7','20Y':'DGS20'}
    yield_pts = {}
    for label, sym in yf_map.items():
        df = _yf_history(sym, period='5d')
        if not df.empty: yield_pts[label] = round(float(df['Close'].dropna().iloc[-1]), 3)
    for label, series in fred_map.items():
        df = _fetch_fred(series, fred_key, limit=5)
        if not df.empty:
            yield_pts[label] = round(float(df['Value'].iloc[-1]), 3)
    # Sort by maturity
    maturity_order = ['1M','3M','6M','1Y','2Y','5Y','7Y','10Y','20Y','30Y']
    sorted_pts = [(m, yield_pts[m]) for m in maturity_order if m in yield_pts]
    if sorted_pts:
        labels_y, vals_y = zip(*sorted_pts)
        fig_yc = go.Figure()
        fig_yc.add_trace(go.Scatter(
            x=list(labels_y), y=list(vals_y),
            mode='lines+markers+text',
            line=dict(color=T['amber'], width=2.5),
            marker=dict(size=8, color=T['amber']),
            text=[f"{v:.2f}%" for v in vals_y],
            textposition='top center',
            textfont=dict(size=10, color=T['white']),
        ))
        fig_yc.update_layout(
            title='US Treasury Yield Curve',
            xaxis_title='Maturity', yaxis_title='Yield (%)',
            paper_bgcolor=T['bg'], plot_bgcolor=T['panel'],
            font=dict(color=T['white'], family='monospace'),
            height=420, margin=dict(l=10,r=10,t=50,b=10),
        )
        st.plotly_chart(fig_yc, use_container_width=True)
        # Metrics
        cols = st.columns(len(sorted_pts))
        for i, (m, v) in enumerate(sorted_pts):
            cols[i].metric(f"{m} Treasury", f"{v:.3f}%")
    # Historical 10Y from FRED
    df10 = _fetch_fred('DGS10', fred_key, limit=500)
    if not df10.empty:
        fig10 = _line_chart_term(df10['Date'], df10['Value'],
                                  'US 10Y Treasury Yield — Historical', 'Yield (%)', T['amber'], 350)
        st.plotly_chart(fig10, use_container_width=True)
    # 2Y-10Y spread (recession indicator)
    df2  = _fetch_fred('DGS2',  fred_key, limit=500)
    df10b = _fetch_fred('T10Y2Y', fred_key, limit=500)
    if not df10b.empty:
        fig_sp = go.Figure(go.Scatter(
            x=df10b['Date'], y=df10b['Value'], mode='lines',
            fill='tozeroy',
            line=dict(color=T['amber'], width=1.5),
            fillcolor='rgba(255,179,0,0.08)',
        ))
        fig_sp.add_hline(y=0, line_color=T['red'], line_dash='dot',
                          annotation_text='Inversion', annotation_font_color=T['red'])
        fig_sp.update_layout(
            title='2Y–10Y Yield Spread (Recession Indicator)',
            xaxis_title='Date', yaxis_title='Spread (%)',
            paper_bgcolor=T['bg'], plot_bgcolor=T['panel'],
            font=dict(color=T['white']), height=320,
        )
        st.plotly_chart(fig_sp, use_container_width=True)


def cmd_commodities(api_keys: dict):
    st.markdown(f"<div class='term-header'>🛢️  CMDTY — COMMODITIES</div>", unsafe_allow_html=True)
    cmdty = [
        ('Crude Oil (WTI)', 'CL=F'),('Brent Crude', 'BZ=F'), ('Natural Gas', 'NG=F'),
        ('Gold',     'GC=F'), ('Silver',   'SI=F'), ('Platinum', 'PL=F'),
        ('Copper',   'HG=F'), ('Corn',     'ZC=F'), ('Wheat',    'ZW=F'),
        ('Soybeans', 'ZS=F'), ('Coffee',   'KC=F'), ('Sugar',    'SB=F'),
    ]
    rows = []
    for name, sym in cmdty:
        df = _yf_history(sym, period='5d')
        if df.empty or len(df) < 2: continue
        prev, last = float(df['Close'].iloc[-2]), float(df['Close'].iloc[-1])
        chg_p = (last-prev)/prev*100
        rows.append({'Commodity': name, 'Symbol': sym, 'Price': f"{last:,.3f}",
                     'Chg': last-prev, 'Chg%': chg_p})
    if not rows: st.error("No commodities data available."); return
    c1,c2,c3,c4 = st.columns(4)
    for i, r in enumerate(rows):
        col=[c1,c2,c3,c4][i%4]
        color = T['green'] if r['Chg'] >= 0 else T['red']
        arrow = '▲' if r['Chg'] >= 0 else '▼'
        col.markdown(
            f"<div class='term-panel' style='padding:8px;text-align:center'>"
            f"<div style='color:{T['amber']};font-family:monospace;font-weight:bold;font-size:11px'>{r['Commodity']}</div>"
            f"<div style='color:{T['white']};font-family:monospace;font-size:14px'>{r['Price']}</div>"
            f"<div style='color:{color};font-family:monospace;font-size:12px'>{arrow} {r['Chg%']:+.2f}%</div>"
            f"</div>", unsafe_allow_html=True)
    st.plotly_chart(_bar_chart_term([r['Commodity'] for r in rows],
        [r['Chg%'] for r in rows], 'Commodities Daily Change (%)'), use_container_width=True)


def cmd_sector(api_keys: dict):
    st.markdown(f"<div class='term-header'>📦  SECTOR — S&P 500 SECTOR PERFORMANCE</div>",
                unsafe_allow_html=True)
    etfs = [
        ('Technology',     'XLK'), ('Healthcare',     'XLV'), ('Financials',    'XLF'),
        ('Consumer Disc.', 'XLY'), ('Industrials',    'XLI'), ('Comm. Services','XLC'),
        ('Consumer Stap.', 'XLP'), ('Energy',         'XLE'), ('Utilities',     'XLU'),
        ('Materials',      'XLB'), ('Real Estate',    'XLRE'),
    ]
    p1, p2 = st.columns(2)
    period = p1.selectbox("Period", ['1d','5d','1mo','3mo','6mo','1y'], index=3, key='sect_period')
    rows   = []
    for name, sym in etfs:
        df = _yf_history(sym, period=period)
        if df.empty or len(df) < 2: continue
        ret = (df['Close'].iloc[-1]/df['Close'].iloc[0]-1)*100
        rows.append({'Sector': name, 'ETF': sym, 'Return%': ret})
    if not rows: st.error("No sector data."); return
    rows.sort(key=lambda x: x['Return%'], reverse=True)
    st.plotly_chart(_bar_chart_term(
        [r['Sector'] for r in rows], [r['Return%'] for r in rows],
        f'S&P 500 Sector Returns — {period}', height=400), use_container_width=True)
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def cmd_econ(indicator: str, api_keys: dict):
    fred_key = api_keys.get('fred', '')
    st.markdown(f"<div class='term-header'>📊  ECON — MACRO INDICATORS</div>",
                unsafe_allow_html=True)
    if indicator.upper() in FRED_SERIES:
        series_id, label = FRED_SERIES[indicator.upper()]
        df = _fetch_fred(series_id, fred_key)
        if df.empty:
            st.error(f"Could not fetch {label} from FRED. "
                     "Add a FRED API key in Settings or check your connection.")
            return
        latest = df['Value'].iloc[-1]
        prev   = df['Value'].iloc[-2] if len(df) > 1 else latest
        chg    = latest - prev
        c1, c2, c3 = st.columns(3)
        c1.metric(label, f"{latest:,.3f}", delta=f"{chg:+.3f}")
        c2.metric("Previous", f"{prev:,.3f}")
        if len(df) > 0:
            c3.metric("Last Updated", str(df['Date'].iloc[-1])[:10])
        fig = _line_chart_term(df['Date'], df['Value'], label, label, T['amber'], 380)
        st.plotly_chart(fig, use_container_width=True)
    elif indicator == '' or indicator.upper() == 'DASHBOARD':
        # Multi-panel macro dashboard
        macro_series = [
            ('GDP Growth','GDPGROWTH','A191RL1Q225SBEA','%'),
            ('CPI (YoY est)','CPI','CPIAUCSL','idx'),
            ('Unemployment','UNRATE','UNRATE','%'),
            ('Fed Funds Rate','FEDFUNDS','FEDFUNDS','%'),
            ('10Y Yield','DGS10','DGS10','%'),
            ('Yield Spread','SPREAD','T10Y2Y','%'),
        ]
        cols = st.columns(3)
        for i, (label, key, sid, unit) in enumerate(macro_series):
            col = cols[i%3]
            df  = _fetch_fred(sid, fred_key, limit=12)
            if df.empty:
                col.metric(label, '—'); continue
            latest = float(df['Value'].iloc[-1])
            prev   = float(df['Value'].iloc[-2]) if len(df)>1 else latest
            chg    = latest - prev
            col.metric(label, f"{latest:,.2f}{unit}", delta=f"{chg:+.2f}{unit}")
        st.markdown("---")
        # Show 3 main charts side by side
        c1, c2 = st.columns(2)
        for col, (label, key, sid, unit) in zip([c1,c2,c1,c2,c1,c2], macro_series):
            df = _fetch_fred(sid, fred_key, limit=120)
            if df.empty: continue
            fig = _line_chart_term(df['Date'], df['Value'], label, f"{label} ({unit})",
                                    T['amber'], 280)
            col.plotly_chart(fig, use_container_width=True)
    else:
        # Try as raw FRED series ID
        df = _fetch_fred(indicator.upper(), fred_key)
        if df.empty:
            st.error(f"Unknown indicator: {indicator}. Try: GDP, CPI, UNRATE, FEDFUNDS, DGS10, SPREAD, M2, OIL, GOLD, VIX, DXY, HOUSING, RETAIL")
            st.markdown(f"Or use `FRED <SERIES_ID>` for any raw FRED series ID.")
            return
        fig = _line_chart_term(df['Date'], df['Value'], indicator.upper(),
                                indicator.upper(), T['amber'], 400)
        st.plotly_chart(fig, use_container_width=True)
        c1,c2,c3 = st.columns(3)
        c1.metric("Latest",   f"{df['Value'].iloc[-1]:,.3f}")
        c2.metric("Previous", f"{df['Value'].iloc[-2]:,.3f}" if len(df)>1 else '—')
        c3.metric("Date",     str(df['Date'].iloc[-1])[:10])


def cmd_fred_raw(series_id: str, api_keys: dict):
    fred_key = api_keys.get('fred','')
    df = _fetch_fred(series_id, fred_key, limit=500)
    if df.empty:
        st.error(f"Could not fetch FRED series: {series_id}"); return
    label = series_id.upper()
    c1,c2,c3 = st.columns(3)
    c1.metric("Latest",   f"{df['Value'].iloc[-1]:,.4f}")
    c2.metric("Previous", f"{df['Value'].iloc[-2]:,.4f}" if len(df)>1 else '—')
    c3.metric("Last Date",str(df['Date'].iloc[-1])[:10])
    st.plotly_chart(_line_chart_term(df['Date'], df['Value'], f"FRED — {label}", label, T['amber'], 420),
                    use_container_width=True)
    with st.expander("Raw data"):
        st.dataframe(df.tail(50).sort_values('Date', ascending=False), use_container_width=True, hide_index=True)


def cmd_market_news(api_keys: dict, query: str = '', category: str = ''):
    """
    NEWS [category|query] — market & world news.
    Priority: NewsAPI (if key set) → yfinance RSS fallback.
    category: top | macro | tech | crypto | earnings  (or any free-text query)
    """
    newsapi_key = api_keys.get('newsapi_key', '').strip()

    # Map user-friendly category keywords → NewsAPI category + search query
    CATEGORY_MAP = {
        'TOP':      ('general',    ''),
        'MACRO':    ('business',   'economy OR "central bank" OR "interest rate" OR GDP OR inflation OR "federal reserve"'),
        'TECH':     ('technology', ''),
        'CRYPTO':   ('',           'bitcoin OR ethereum OR crypto OR cryptocurrency OR blockchain'),
        'EARNINGS': ('business',   'earnings OR "quarterly results" OR revenue OR profit OR EPS'),
    }

    # Determine display header
    if query:
        disp = f"NEWS — {query.upper()}"
    elif category:
        disp = f"NEWS — {category.upper()}"
    else:
        disp = "NEWS — MARKET & WORLD"

    st.markdown(f"<div class='term-header'>📰  {disp}</div>", unsafe_allow_html=True)

    # Resolve category/query for NewsAPI
    na_cat, na_q = '', ''
    if category in CATEGORY_MAP:
        na_cat, na_q = CATEGORY_MAP[category]
    elif category:
        # Unknown category word → treat as free-text search
        na_q = category
    if query:
        # Free text always goes to /everything search
        na_q    = query
        na_cat  = ''

    used_newsapi = False
    articles = []

    # ── Primary: NewsAPI ────────────────────────────────────────────────────────
    if newsapi_key:
        articles = _fetch_newsapi(na_q or '', newsapi_key,
                                   category=na_cat, page_size=25)
        used_newsapi = bool(articles)

    # ── Fallback: yfinance RSS ─────────────────────────────────────────────────
    if not articles:
        syms     = ['SPY', 'QQQ', 'DIA', 'BTC-USD']
        yf_news  = []
        seen     = set()
        for sym in syms:
            for n in _yf_news(sym):
                t = n.get('title', '')
                if t and t not in seen:
                    seen.add(t)
                    ts = n.get('providerPublishTime', 0)
                    dt = datetime.fromtimestamp(ts).strftime('%Y-%m-%dT%H:%M:%S') if ts else ''
                    yf_news.append({
                        'title':       t,
                        'source':      n.get('publisher', ''),
                        'publishedAt': dt,
                        'url':         n.get('link', ''),
                        'description': '',
                    })
        yf_news.sort(key=lambda x: x['publishedAt'], reverse=True)
        articles = yf_news[:25]

    if not articles:
        st.info("No news available at this time. "
                "Add a NewsAPI key in Terminal → API Keys for premium headlines.")
        return

    # ── Render articles ────────────────────────────────────────────────────────
    if used_newsapi and not newsapi_key:
        pass  # already warned above
    elif not used_newsapi and not newsapi_key:
        st.caption(
            "💡 Add a **NewsAPI key** (free at [newsapi.org](https://newsapi.org/register)) "
            "in Terminal → API Keys for richer, real-time headlines. "
            "Currently showing yfinance RSS as fallback.")

    for art in articles:
        dt_str  = _fmt_newsapi_dt(art.get('publishedAt', ''))
        src     = art.get('source', '')
        title   = art.get('title', '')
        desc    = art.get('description', '')
        link    = art.get('url', '')
        desc_html = (
            f"<br><span style='color:{T['muted']};font-family:monospace;font-size:11px'>"
            f"{desc[:160]}{'…' if len(desc) > 160 else ''}</span>"
        ) if desc else ''
        link_html = (
            f"  <a href='{link}' target='_blank' "
            f"style='color:{T['blue']}'>↗</a>"
        ) if link else ''

        st.markdown(
            f"<div class='term-panel' style='padding:8px 12px'>"
            f"<span class='term-lbl'>{dt_str} &nbsp;|&nbsp; {src}</span><br>"
            f"<span style='color:{T['white']};font-family:monospace;font-size:13px'>"
            f"{title}</span>{link_html}{desc_html}"
            f"</div>",
            unsafe_allow_html=True)

    # Source badge hint
    if used_newsapi:
        st.markdown(
            f"<div style='margin-top:6px;font-family:monospace;font-size:10px;"
            f"color:{T['muted']}'>📡 NewsAPI &nbsp;|&nbsp; "
            f"<a href='https://newsapi.org' target='_blank' "
            f"style='color:{T['blue']}'>newsapi.org</a> 🔑</div>",
            unsafe_allow_html=True)



def cmd_screen(api_keys: dict):
    """Basic stock screener using yfinance bulk downloads of S&P 500 universe."""
    st.markdown(f"<div class='term-header'>🔎  SCREEN — STOCK SCREENER</div>",
                unsafe_allow_html=True)
    st.caption("Screens a sample of large-cap US stocks. Add your own list for deeper coverage.")
    universe = ['AAPL','MSFT','AMZN','GOOG','META','NVDA','TSLA','BRK-B','JPM','JNJ',
                'V','PG','MA','UNH','XOM','HD','CVX','MRK','LLY','ABBV',
                'KO','PEP','AVGO','COST','MCD','TMO','ACN','WMT','ABT','CRM',
                'ORCL','NFLX','AMD','INTC','QCOM','TXN','AMGN','GILD','SBUX','NKE',
                'GS','MS','BAC','WFC','C','USB','AXP','BLK','SCHW','CB',
                'SPG','PLD','AMT','EQIX','O','DLR','PSA','EXR','VICI','WPC']
    c1,c2,c3,c4 = st.columns(4)
    min_mktcap = c1.number_input("Min Market Cap ($B)", 0.0, 3000.0, 10.0, 10.0, key='scr_mc')
    max_pe     = c2.number_input("Max P/E Ratio",        0.0, 1000.0, 50.0, 5.0,  key='scr_pe')
    min_beta   = c3.number_input("Min Beta",             -2.0, 5.0,    0.0, 0.1,  key='scr_b1')
    max_beta   = c4.number_input("Max Beta",             -2.0, 5.0,    3.0, 0.1,  key='scr_b2')
    if not st.button("▶ Run Screen", type="primary", key='scr_run'): return
    rows = []
    progress = st.progress(0)
    for i, sym in enumerate(universe):
        progress.progress((i+1)/len(universe))
        info = _yf_info(sym)
        if not info: continue
        mc  = _safe_get(info,'marketCap', default=0) or 0
        pe  = _safe_get(info,'trailingPE') or np.nan
        beta= _safe_get(info,'beta')       or np.nan
        div = (_safe_get(info,'dividendYield') or 0) * 100
        roe = (_safe_get(info,'returnOnEquity') or 0) * 100
        rev = _safe_get(info,'totalRevenue')
        if mc < min_mktcap * 1e9: continue
        if not np.isnan(pe) and pe > max_pe: continue
        if not np.isnan(beta) and not (min_beta <= beta <= max_beta): continue
        rows.append({
            'Symbol':     sym,
            'Name':       _safe_get(info,'shortName', default='')[:25],
            'Price':      f"${_safe_get(info,'currentPrice',default=0):,.2f}",
            'Mkt Cap':    _fmt_large(mc),
            'P/E':        f"{pe:.1f}" if not np.isnan(pe) else '—',
            'Beta':       f"{beta:.2f}" if not np.isnan(beta) else '—',
            'Div Yield':  f"{div:.2f}%" if div else '—',
            'ROE':        f"{roe:.1f}%" if roe else '—',
            'Revenue':    _fmt_large(rev),
        })
    progress.empty()
    if rows:
        st.success(f"✅ {len(rows)} stocks matched your criteria.")
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.warning("No stocks matched. Try relaxing the filters.")


def cmd_port_monitor(api_keys: dict):
    """Live monitor of the user's loaded strategy symbols."""
    ss = st.session_state
    st.markdown(f"<div class='term-header'>🗂️  PORT — STRATEGY MONITOR</div>",
                unsafe_allow_html=True)
    if not ss.portfolio_strategies:
        st.info("No portfolio loaded. Go to Portfolio Analysis → Load Strategy Data first.")
        return
    st.write(f"Monitoring {len(ss.portfolio_strategies)} strategy series.")
    df_p = ss.portfolio_price_df
    if df_p is None:
        st.error("Portfolio price data not in session."); return
    fig = go.Figure()
    COLORS = [T['amber'],T['green'],T['blue'],T['red'],'#ce93d8','#80cbc4']
    for i, col in enumerate(df_p.columns):
        fig.add_trace(go.Scatter(
            x=df_p.index, y=df_p[col], name=col,
            line=dict(color=COLORS[i%len(COLORS)], width=2),
        ))
    fig.update_layout(
        title='Loaded Portfolio Strategies (Normalised to 100)',
        paper_bgcolor=T['bg'], plot_bgcolor=T['panel'],
        font=dict(color=T['white'], family='monospace'),
        height=500, hovermode='x unified',
    )
    st.plotly_chart(fig, use_container_width=True)
    st.dataframe(df_p.tail(10), use_container_width=True)


# ── Alert commands ─────────────────────────────────────────────────────────────

def cmd_list_alerts(user_id: int):
    """LIST ALERT — show all active price alerts for the current user."""
    st.markdown("<div class='term-header'>🔔  PRICE ALERTS</div>", unsafe_allow_html=True)
    alerts = get_user_alerts(user_id)
    if not alerts:
        st.markdown(
            f"<div class='term-panel'><span style='color:{T['muted']};font-family:monospace'>"
            f"No active alerts. Use  <b style='color:{T['amber']}'>TICKER ADD_ALERT EVERY N%</b>"
            f"  to add one.</span></div>", unsafe_allow_html=True)
        return

    for a in alerts:
        baseline = a['baseline_price']
        interval = a['pct_interval']
        mul      = a['last_triggered_multiple']
        fired    = f"Last fired at ×{mul} ({interval*mul:.1f}%)" if mul else "Not yet triggered today"
        created  = str(a['created_at'])[:10]

        try:
            current, src = _fetch_current_price(a['ticker'])
            src_icons = {'pre-market': '🌅', 'regular': '📈',
                         'prev-close': '🔒', 'unknown': '—'}
            src_label = src_icons.get(src, '') + f' {src}'
            if current and baseline:
                chg = (current - baseline) / baseline * 100
                price_str  = f"${current:,.4f}  ({chg:+.2f}%)  <span style='color:{T['muted']};font-size:10px'>{src_label}</span>"
                price_color = T['green'] if chg >= 0 else T['red']
            else:
                price_str  = "—"
                price_color = T['muted']
        except:
            price_str  = "—"
            price_color = T['muted']

        st.markdown(
            f"<div class='term-panel'>"
            f"<span style='color:{T['amber']};font-family:monospace;font-size:14px;font-weight:bold'>"
            f"🔔 {a['ticker']}</span>"
            f"<span style='color:{T['muted']};font-family:monospace;font-size:11px;float:right'>"
            f"Added {created}</span><br>"
            f"<span style='color:{T['white']};font-family:monospace'>Alert every </span>"
            f"<span style='color:{T['amber']};font-family:monospace;font-weight:bold'>{interval}%</span>"
            f"<span style='color:{T['muted']};font-family:monospace'> &nbsp;|&nbsp; "
            f"Baseline: ${baseline:,.4f} &nbsp;|&nbsp; "
            f"Now: </span><span style='color:{price_color};font-family:monospace'>{price_str}</span><br>"
            f"<span style='color:{T['muted']};font-family:monospace;font-size:11px'>{fired}</span>"
            f"</div>", unsafe_allow_html=True)


def _fetch_current_price(ticker: str) -> tuple[float | None, str]:
    """
    Fetch best available price for display in LIST ALERT.
    Returns (price, source_label).  Pre-market price takes priority.
    """
    try:
        import yfinance as yf
        fi = yf.Ticker(ticker).fast_info

        pre = getattr(fi, 'pre_market_price', None)
        if pre and float(pre) > 0:
            return float(pre), 'pre-market'

        last = getattr(fi, 'last_price', None)
        if last and float(last) > 0:
            return float(last), 'regular'

        prev = getattr(fi, 'previous_close', None)
        if prev and float(prev) > 0:
            return float(prev), 'prev-close'
    except:
        pass
    return None, 'unknown'


def cmd_add_alert(ticker: str, pct_interval: float, user_id: int):
    """TICKER ADD_ALERT EVERY N% — register a price alert."""
    current, src = _fetch_current_price(ticker)
    if current is None:
        st.error(f"❌ Could not fetch current price for **{ticker}**. Check the symbol.")
        return

    src_labels = {'pre-market': '🌅 pre-market', 'regular': '📈 regular market',
                  'prev-close': '🔒 previous close', 'unknown': '—'}
    src_display = src_labels.get(src, src)

    ok, msg = add_price_alert(user_id, ticker, pct_interval, current)
    if ok:
        st.markdown(
            f"<div class='term-panel'>"
            f"<span style='color:{T['green']};font-family:monospace;font-size:14px'>✅ Alert set!</span><br>"
            f"<span style='color:{T['white']};font-family:monospace'>"
            f"You will receive an email every time <b style='color:{T['amber']}'>{ticker}</b> "
            f"moves ±{pct_interval}%, ±{pct_interval*2}%, ±{pct_interval*3}%… from today's baseline.<br>"
            f"Baseline price locked at: <b style='color:{T['amber']}'>${current:,.4f}</b> "
            f"<span style='color:{T['muted']};font-size:11px'>({src_display})</span><br>"
            f"Pre-market prices are monitored. Alerts reset daily at midnight.</span>"
            f"</div>", unsafe_allow_html=True)
    else:
        st.error(f"Failed to add alert: {msg}")


def cmd_remove_alert(ticker: str, user_id: int):
    """TICKER REMOVE_ALERT — deactivate all alerts on that ticker."""
    ok, msg = remove_price_alert(user_id, ticker)
    if ok:
        st.markdown(
            f"<div class='term-panel'>"
            f"<span style='color:{T['amber']};font-family:monospace'>🗑️ {msg}</span>"
            f"</div>", unsafe_allow_html=True)
    else:
        st.error(msg)


# ── Source badge ───────────────────────────────────────────────────────────────

def _source_badge(sources: list):
    """Render a small footer strip showing exactly which APIs supplied the data.

    Each entry in ``sources`` is a dict with:
      name     – display label
      url      – link to the API / service docs
      key_used – True when a user-supplied API key was used (shows 🔑 vs 🌐)
    """
    items = []
    for s in sources:
        icon    = "🔑" if s.get('key_used') else "🌐"
        suffix  = " <span style='color:#4ade80;font-size:10px'>(authenticated)</span>" \
                  if s.get('key_used') else \
                  " <span style='color:#94a3b8;font-size:10px'>(public)</span>"
        items.append(
            f'<a href="{s["url"]}" target="_blank" '
            f'style="color:{T["blue"]};font-family:monospace;font-size:11px;'
            f'text-decoration:none;margin-right:16px">'
            f'{icon}&nbsp;{s["name"]}</a>{suffix}'
        )
    label = "Data sources" if len(sources) > 1 else "Data source"
    st.markdown(
        f"<div style='margin-top:14px;padding:7px 14px;"
        f"border-top:1px solid {T['border']};"
        f"font-family:monospace;font-size:11px;color:{T['muted']}'>"
        f"📡 &nbsp;<b style='color:{T['muted']}'>{label}:</b> &nbsp;"
        + " &nbsp;".join(items) +
        f"</div>",
        unsafe_allow_html=True,
    )


# ── Command parser ─────────────────────────────────────────────────────────────

def parse_and_run_command(raw: str, api_keys: dict):
    """Parse a   -style command string and dispatch to the right handler."""
    parts = raw.strip().upper().split()
    if not parts: return

    cmd0 = parts[0]

    has_av   = bool(api_keys.get('alpha_vantage', ''))
    has_fmp  = bool(api_keys.get('fmp', ''))
    has_fred = bool(api_keys.get('fred', ''))
    has_alp  = bool(api_keys.get('alpaca_key', '')) and bool(api_keys.get('alpaca_secret', ''))

    YF_SRC   = {'name': 'yfinance',       'url': 'https://pypi.org/project/yfinance/',                    'key_used': False}
    FRED_SRC = {'name': 'FRED',            'url': 'https://fred.stlouisfed.org',                           'key_used': has_fred}
    AV_SRC   = {'name': 'Alpha Vantage',   'url': 'https://www.alphavantage.co',                           'key_used': has_av}
    FMP_SRC  = {'name': 'FMP',             'url': 'https://financialmodelingprep.com',                     'key_used': has_fmp}
    ALP_SRC  = {'name': 'Alpaca Markets',  'url': 'https://alpaca.markets',                                'key_used': has_alp}
    INT_SRC  = {'name': 'Internal (strategy data)', 'url': 'https://github.com',                           'key_used': False}
    CG_SRC   = {'name': 'CoinGecko',       'url': 'https://www.coingecko.com',                             'key_used': False}
    GDELT_SRC = {'name': 'GDELT',          'url': 'https://www.gdeltproject.org',                          'key_used': False}
    RSS_SRC  = {'name': 'RSS Feeds',       'url': 'https://en.wikipedia.org/wiki/RSS',                    'key_used': False}
    WB_SRC   = {'name': 'World Bank',      'url': 'https://data.worldbank.org',                            'key_used': False}

    # HELP
    if cmd0 == 'HELP':
        st.markdown(f"<div class='term-header'>📟  TERMINAL HELP</div>", unsafe_allow_html=True)
        st.code(COMMAND_HELP, language='')
        return

    # NEWS (market-wide) — with optional category / free-text query
    # e.g.  NEWS | NEWS TOP | NEWS MACRO | NEWS TECH | NEWS federal reserve
    if cmd0 == 'NEWS':
        has_news = bool(api_keys.get('newsapi_key', '').strip())
        NEWS_SRC = {'name': 'NewsAPI', 'url': 'https://newsapi.org', 'key_used': has_news}
        NEWS_CATEGORIES = {'TOP', 'MACRO', 'TECH', 'CRYPTO', 'EARNINGS'}
        if len(parts) == 1:
            cmd_market_news(api_keys, query='', category='')
        elif parts[1] == 'FEED':
            cmd_news_feed(api_keys)
            _source_badge([RSS_SRC, GDELT_SRC, YF_SRC])
            return
        elif parts[1] == 'SENTIMENT':
            query = ' '.join(raw.strip().split()[2:]) if len(parts) > 2 else 'finance markets'
            cmd_news_sentiment(query)
            _source_badge([GDELT_SRC, YF_SRC])
            return
        elif parts[1] in NEWS_CATEGORIES:
            cmd_market_news(api_keys, query='', category=parts[1])
        else:
            raw_parts = raw.strip().split()
            free_query = ' '.join(raw_parts[1:])
            cmd_market_news(api_keys, query=free_query, category='')
        _source_badge([NEWS_SRC, YF_SRC])
        return

    # WEI
    if cmd0 == 'WEI':
        cmd_wei(api_keys)
        _source_badge([YF_SRC])
        return

    # FX
    if cmd0 == 'FX':
        cmd_fx(api_keys)
        _source_badge([YF_SRC])
        return

    # CRYPTO
    if cmd0 in ('CRYPTO','BTC','ETH'):
        if len(parts) > 1:
            sub = parts[1].upper()
            if sub == 'TOP':
                cmd_crypto_top(api_keys)
                _source_badge([CG_SRC, YF_SRC])
                return
        cmd_crypto(api_keys)
        _source_badge([YF_SRC, CG_SRC])
        return

    # COIN <name> — single-coin deep dive via CoinGecko
    if cmd0 == 'COIN':
        coin = parts[1] if len(parts) > 1 else 'bitcoin'
        cmd_coin(coin)
        _source_badge([CG_SRC, YF_SRC])
        return

    # RATES — yfinance for the main tenors, FRED for the rest
    if cmd0 == 'RATES':
        cmd_rates(api_keys)
        _source_badge([YF_SRC, FRED_SRC])
        return

    # CMDTY / COMMODITIES
    if cmd0 in ('CMDTY','COMMODITIES','COMM'):
        cmd_commodities(api_keys)
        _source_badge([YF_SRC])
        return

    # SECTOR
    if cmd0 in ('SECTOR','SECTORS'):
        cmd_sector(api_keys)
        _source_badge([YF_SRC])
        return

    # MOVERS
    if cmd0 == 'MOVERS':
        cat = parts[1].lower() if len(parts) > 1 else 'gainers'
        cmd_movers(cat, api_keys)
        _source_badge([YF_SRC])
        return

    # ECON [indicator|GLOBAL]
    if cmd0 == 'ECON':
        if len(parts) > 1 and parts[1] == 'GLOBAL':
            cmd_econ_global(api_keys)
            _source_badge([WB_SRC, FRED_SRC])
            return
        indicator = parts[1] if len(parts) > 1 else ''
        cmd_econ(indicator, api_keys)
        _source_badge([FRED_SRC])
        return

    # SENTIMENT <ticker> — news sentiment analysis
    if cmd0 == 'SENTIMENT':
        ticker = parts[1] if len(parts) > 1 else 'SPY'
        cmd_sentiment(ticker)
        _source_badge([GDELT_SRC, YF_SRC])
        return

    # FRED <series_id>
    if cmd0 == 'FRED' and len(parts) > 1:
        cmd_fred_raw(parts[1], api_keys)
        _source_badge([FRED_SRC])
        return

    # SCREEN / SEARCH / IV — handled directly in terminal_page (have internal buttons)
    if cmd0 in ('SCREEN', 'SEARCH', 'IV'):
        return   # already rendered by the persistent block above

    # PORT
    if cmd0 == 'PORT':
        cmd_port_monitor(api_keys)
        _source_badge([INT_SRC])
        return

    # ── New features ────────────────────────────────────────────────────────

    # WL [ADD/REMOVE ticker]
    if cmd0 == 'WL':
        user_id = st.session_state.get('user_id')
        if not user_id: st.error("Please log in."); return
        cmd_wl(parts, user_id)
        _source_badge([YF_SRC])
        return

    # EARN [ticker]
    if cmd0 == 'EARN':
        user_id = st.session_state.get('user_id')
        if not user_id: st.error("Please log in."); return
        cmd_earn(parts, user_id)
        _source_badge([YF_SRC])
        return

    # ECAL
    if cmd0 == 'ECAL':
        cmd_ecal(api_keys)
        _source_badge([FRED_SRC])
        return

    # PNL [ADD/REMOVE ticker ...]
    if cmd0 == 'PNL':
        user_id = st.session_state.get('user_id')
        if not user_id: st.error("Please log in."); return
        cmd_pnl(parts, user_id)
        _source_badge([YF_SRC])
        return

    # CORR [tickers...] [period]
    if cmd0 == 'CORR':
        user_id = st.session_state.get('user_id')
        if not user_id: st.error("Please log in."); return
        cmd_corr(parts, user_id, api_keys)
        _source_badge([YF_SRC])
        return

    # VOL [ticker] [period]
    if cmd0 == 'VOL':
        cmd_vol(parts, api_keys)
        _source_badge([YF_SRC])
        return

    # TOP — today's top market news
    if cmd0 == 'TOP':
        cmd_top(api_keys)
        _source_badge([YF_SRC])
        return

    # ANR TICKER — analyst recommendations
    if cmd0 == 'ANR':
        cmd_anr(parts)
        _source_badge([YF_SRC])
        return

    # RV TICKER [peers] — relative value peer comparison
    if cmd0 == 'RV':
        cmd_rv(parts)
        _source_badge([YF_SRC])
        return

    # IPO — IPO calendar
    if cmd0 == 'IPO':
        cmd_ipo(api_keys)
        _source_badge([YF_SRC])
        return

    # INSIDER TICKER — insider transactions
    if cmd0 == 'INSIDER':
        cmd_insider(parts)
        _source_badge([YF_SRC])
        return

    # SHORT TICKER — short interest
    if cmd0 == 'SHORT':
        cmd_short(parts)
        _source_badge([YF_SRC])
        return

    # TRA TICKER [benchmarks] [period] — total return analysis
    if cmd0 == 'TRA':
        cmd_tra(parts)
        _source_badge([YF_SRC])
        return

    # RISK TICKER [benchmark] — risk dashboard
    if cmd0 == 'RISK':
        cmd_risk(parts)
        _source_badge([YF_SRC])
        return

    # IND — Index lookup
    if cmd0 == 'IND':
        cmd_ind(parts, api_keys)
        _source_badge([YF_SRC])
        return

    # WB — World bond yields
    if cmd0 == 'WB':
        cmd_wb(parts, api_keys)
        _source_badge([YF_SRC, FRED_SRC])
        return

    # OAS — Option-adjusted spread
    if cmd0 == 'OAS':
        cmd_oas(parts, api_keys)
        _source_badge([FRED_SRC])
        return

    # OASD — Option-adjusted spread duration
    if cmd0 == 'OASD':
        cmd_oasd(parts, api_keys)
        _source_badge([FRED_SRC])
        return

    # LIST ALERT — show user's active alerts
    if cmd0 == 'LIST' and len(parts) > 1 and parts[1] == 'ALERT':
        user_id = st.session_state.get('user_id')
        if not user_id:
            st.error("Please log in to view alerts.")
            return
        cmd_list_alerts(user_id)
        return

    # Security commands: TICKER [FUNCTION] [args...]
    ticker = cmd0.replace('.US','').replace(' US EQUITY','')
    for suffix in (' EQUITY',' INDEX',' COMDTY',' CURNCY'):
        if ticker.endswith(suffix):
            ticker = ticker.replace(suffix,'').strip()

    func = parts[1] if len(parts) > 1 else 'OV'

    # TICKER ADD_ALERT EVERY N%  — e.g. NFLX ADD_ALERT EVERY 2%
    if func == 'ADD_ALERT':
        user_id = st.session_state.get('user_id')
        if not user_id:
            st.error("Please log in to set alerts."); return
        # Find the percentage: last token, strip '%'
        pct_str = parts[-1].replace('%', '')
        try:
            pct = float(pct_str)
            if pct <= 0: raise ValueError
        except ValueError:
            st.error(f"Invalid percentage: '{parts[-1]}'. Example: NFLX ADD_ALERT EVERY 2%")
            return
        cmd_add_alert(ticker, pct, user_id)
        return

    # TICKER REMOVE_ALERT
    if func == 'REMOVE_ALERT':
        user_id = st.session_state.get('user_id')
        if not user_id:
            st.error("Please log in to remove alerts."); return
        cmd_remove_alert(ticker, user_id)
        return

    if func == 'GP':
        period = parts[2].lower() if len(parts) > 2 else '1y'
        cmd_chart(ticker, period, api_keys)
        _source_badge([YF_SRC])
    elif func in ('DES', 'DESCRIPTION'):
        cmd_description(ticker, api_keys)
        srcs = [YF_SRC] + ([FMP_SRC] if has_fmp else [])
        _source_badge(srcs)
    elif func in ('FA', 'FINANCIALS'):
        cmd_financials(ticker, api_keys)
        _source_badge([YF_SRC])
    elif func in ('NEWS',):
        cmd_news(ticker, api_keys)
        has_news = bool(api_keys.get('newsapi_key', '').strip())
        NEWS_SRC = {'name': 'NewsAPI', 'url': 'https://newsapi.org', 'key_used': has_news}
        srcs = [NEWS_SRC, YF_SRC] + ([AV_SRC] if has_av else [])
        _source_badge(srcs)
    elif func in ('OPT', 'OPTIONS'):
        cmd_options(ticker, api_keys)
        _source_badge([YF_SRC])
    elif func in ('DVD', 'DIVIDENDS'):
        cmd_dividends(ticker, api_keys)
        _source_badge([YF_SRC])
    elif func in ('COMP', 'COMPARE'):
        peers = [p for p in parts[2:]] if len(parts) > 2 else []
        cmd_compare([ticker] + peers, api_keys)
        _source_badge([YF_SRC])
    else:
        # Default: OV (overview)
        cmd_overview(ticker, api_keys)
        srcs = [YF_SRC] + ([FMP_SRC] if has_fmp else []) + ([ALP_SRC] if has_alp else [])
        _source_badge(srcs)


# ── Terminal Page ──────────────────────────────────────────────────────────────

def terminal_page():
    ss = st.session_state
    st.markdown(TERM_CSS, unsafe_allow_html=True)

    # ── Top bar ────────────────────────────────────────────────────────────
    hdr_bg  = T['header']; hdr_am = T['amber']
    hdr_wh  = T['white'];  hdr_mu = T['muted']
    now_utc = datetime.utcnow().strftime('%Y-%m-%d  %H:%M UTC')
    st.markdown(
        f"<div style='background:{hdr_bg};padding:8px 16px;border-radius:6px;"
        f"font-family:monospace;color:{hdr_am};font-size:15px;font-weight:bold;"
        f"letter-spacing:2px;margin-bottom:8px'>"
        f"📟 &nbsp; STRATEGY TERMINAL  &nbsp;|&nbsp; "
        f"<span style='color:{hdr_wh};font-size:12px'>"
        f"yfinance · FRED · CoinGecko · GDELT · RSS · World Bank · "
        f"Alpha Vantage · FMP · Polygon.io · NewsAPI</span>"
        f"&nbsp;|&nbsp;<span style='color:{hdr_mu};font-size:11px'>"
        f"{now_utc}</span>"
        f"</div>", unsafe_allow_html=True)

    # ── Quick-access buttons grouped into 3 logical rows ──────────────────────
    # Each entry: (display_label, command_to_run)
    fkey_rows = [
        # Row 1 — Markets & Data
        [
            ('HELP',   'HELP'),   ('WEI',    'WEI'),   ('FX',     'FX'),
            ('CRYPTO', 'CRYPTO'), ('CRYPTO TOP', 'CRYPTO TOP'), ('RATES',  'RATES'),
            ('CMDTY',  'CMDTY'),  ('SECTOR', 'SECTOR'), ('MOVERS', 'MOVERS'),
            ('ECON',   'ECON'),   ('ECON GLOBAL','ECON GLOBAL'), ('SCREEN', 'SCREEN'),
        ],
        # Row 2 — News & Events
        [
            ('NEWS',       'NEWS'),      ('NEWS TOP',   'NEWS TOP'),
            ('NEWS MACRO', 'NEWS MACRO'),('NEWS TECH',  'NEWS TECH'),
            ('NEWS FEED',  'NEWS FEED'),  ('TOP',        'TOP'),
            ('IPO',        'IPO'),       ('ECAL',       'ECAL'),
            ('EARN',       'EARN'),      ('SEARCH',     'SEARCH'),
        ],
        # Row 3 — Analysis & Portfolio
        [
            ('WL',   'WL'),  ('PNL',  'PNL'), ('PORT', 'PORT'),
            ('VOL',  'VOL'), ('IV',   'IV'),  ('CORR', 'CORR'),
            ('ANR',  'ANR'), ('RV',   'RV'),  ('TRA',  'TRA'),
            ('RISK', 'RISK'),
        ],
        # Row 4 — Indices & Fixed Income
        [
            ('IND',  'IND'), ('WB',   'WB'),  ('OAS',  'OAS'),
            ('OASD', 'OASD'),
        ],
    ]
    fkeys = [item for row in fkey_rows for item in row]
    ROW_LABELS = ['📊 Markets & Data', '📰 News & Events', '🔬 Analysis & Portfolio',
                  '📈 Indices & Fixed Income']

    # ── Command input with autocomplete ───────────────────────────────────────
    # Suggestion dropdown is OUTSIDE the form → selecting fills value, never submits.
    # Form text_input + submit button → ONLY Enter or ▶ Run triggers execution.
    st.markdown("")

    def _on_suggest_change():
        chosen = ss.get('term_suggest_box', '')
        if chosen and chosen != '— pick a command —':
            extracted = chosen.split('  —  ')[0].strip()
            ss['_cmd_val'] = extracted
            ss['_input_gen'] = ss.get('_input_gen', 0) + 1

    # ── Suggestion dropdown (outside form) ────────────────────────────────
    current_val = ss.get('_cmd_val', '')
    typed_up    = current_val.strip().upper()
    matches     = []

    if typed_up:
        import re as _re
        parts_typed = typed_up.split()
        first = parts_typed[0]
        rest  = parts_typed[1:]
        is_ticker = bool(_re.match(r'^[A-Z]{1,5}$', first))

        if is_ticker and first not in (
            'WL','PNL','VOL','WEI','FX','NEWS','HELP','EARN','ECAL',
            'CORR','ECON','FRED','RATES','CMDTY','SECTOR','MOVERS',
            'SCREEN','PORT','CRYPTO','LIST','SEARCH','IV','TOP','ANR',
            'RV','IPO','INSIDER','SHORT','TRA','RISK',
            'IND','WB','OAS','OASD','COIN','SENTIMENT',
        ):
            ticker = first
            sub    = rest[0] if rest else ''
            ticker_cmds = [
                (f"{ticker}",                    f"{ticker} — overview (price, stats, financials)"),
                (f"{ticker} GP",                 f"{ticker} — price chart (default 1y)"),
                (f"{ticker} GP 1d",              f"{ticker} — intraday chart"),
                (f"{ticker} GP 5d",              f"{ticker} — 5-day chart"),
                (f"{ticker} GP 1mo",             f"{ticker} — 1-month chart"),
                (f"{ticker} GP 3mo",             f"{ticker} — 3-month chart"),
                (f"{ticker} GP 6mo",             f"{ticker} — 6-month chart"),
                (f"{ticker} GP 1y",              f"{ticker} — 1-year chart"),
                (f"{ticker} GP 2y",              f"{ticker} — 2-year chart"),
                (f"{ticker} GP 5y",              f"{ticker} — 5-year chart"),
                (f"{ticker} DES",                f"{ticker} — company description & key info"),
                (f"{ticker} FA",                 f"{ticker} — financials (income / balance / cash)"),
                (f"{ticker} NEWS",               f"{ticker} — latest news headlines"),
                (f"{ticker} OPT",                f"{ticker} — options chain"),
                (f"{ticker} DVD",                f"{ticker} — dividend history"),
                (f"{ticker} COMP MSFT AAPL",     f"{ticker} — compare vs MSFT, AAPL"),
                (f"VOL {ticker}",                f"{ticker} — volatility: RV, IV, distribution, surface"),
                (f"VOL {ticker} 6mo",            f"{ticker} — vol analysis 6-month lookback"),
                (f"EARN {ticker}",               f"{ticker} — earnings date + EPS history"),
                (f"WL ADD {ticker}",             f"Add {ticker} to watchlist"),
                (f"WL REMOVE {ticker}",          f"Remove {ticker} from watchlist"),
                (f"PNL ADD {ticker} 100 0.00",   f"Add {ticker} position (qty=100, fill cost)"),
                (f"PNL REMOVE {ticker}",         f"Remove {ticker} from P&L"),
                (f"{ticker} ADD_ALERT EVERY 2%", f"{ticker} — alert every 2% price move"),
                (f"{ticker} ADD_ALERT EVERY 5%", f"{ticker} — alert every 5% price move"),
                (f"{ticker} REMOVE_ALERT",       f"{ticker} — remove all price alerts"),
                (f"CORR {ticker} SPY QQQ",       f"{ticker} — correlation vs SPY, QQQ"),
                (f"ANR {ticker}",                 f"{ticker} — analyst ratings & price targets"),
                (f"RV {ticker}",                  f"{ticker} — relative value vs sector peers"),
                (f"INSIDER {ticker}",             f"{ticker} — insider buying/selling"),
                (f"SHORT {ticker}",               f"{ticker} — short interest + squeeze gauge"),
                (f"TRA {ticker}",                 f"{ticker} — total return vs SPY + QQQ"),
                (f"TRA {ticker} SPY QQQ 5y",      f"{ticker} — total return 5Y custom benchmarks"),
                (f"RISK {ticker}",                f"{ticker} — risk: beta, VaR, scatter vs SPY"),
                (f"RISK {ticker} QQQ",            f"{ticker} — risk vs QQQ benchmark"),
            ]
            if sub:
                matches = [f"{c}  —  {d}" for c, d in ticker_cmds if sub in c.upper()][:12]
            else:
                matches = [f"{c}  —  {d}" for c, d in ticker_cmds][:12]
        else:
            matches = [
                f"{c}  —  {d}"
                for c, d in COMMAND_SUGGESTIONS
                if typed_up in c.upper() or typed_up in d.upper()
            ][:12]

    if matches:
        st.selectbox(
            "Suggestions",
            options=["— pick a command —"] + matches,
            index=0,
            key="term_suggest_box",
            label_visibility="collapsed",
            on_change=_on_suggest_change,
        )

    # ── Form: text input + Run button — only Enter or click submits ────────
    with st.form(key="cmd_form", clear_on_submit=False):
        fi1, fi2 = st.columns([5, 1])
        with fi1:
            input_key = f"term_input_{ss.get('_input_gen', 0)}"
            typed_form = st.text_input(
                "⌨️  Command",
                value=ss.get('_cmd_val', ''),
                placeholder="Type command e.g.  AAPL GP 1y  |  VOL TSLA  |  WL  |  HELP",
                key=input_key,
                label_visibility="collapsed",
            )
        with fi2:
            run = st.form_submit_button(
                "▶  Run", type="primary", use_container_width=True)

    # After form renders, sync typed value for suggestion filtering next cycle
    if not run:
        ss['_cmd_val'] = typed_form

    cmd_input = typed_form.strip()

    # ── Quick-access buttons — 3 grouped rows ────────────────────────────────
    _fk_label_css = """
<style>
.fkrow-label {
    font-family: monospace; font-size: 9px; color: #ffb300;
    letter-spacing: 1.5px; text-transform: uppercase;
    margin: 8px 0 1px 2px; font-weight: bold;
}
</style>
"""
    st.markdown(_fk_label_css, unsafe_allow_html=True)

    for row_idx, (row_label, row_btns) in enumerate(zip(ROW_LABELS, fkey_rows)):
        st.markdown(f"<div class='fkrow-label'>{row_label}</div>", unsafe_allow_html=True)
        cols_fk = st.columns(len(row_btns))
        for col, (lbl, cmd) in zip(cols_fk, row_btns):
            if col.button(lbl, key=f"fk_{lbl.replace(' ','_')}", use_container_width=True):
                ss.term_cmd       = cmd
                ss['_cmd_val']    = cmd
                ss['_input_gen']  = ss.get('_input_gen', 0) + 1
                ss['_should_run'] = True
                ss.term_history.append(cmd)
                st.rerun()

    # ── Style all fkey buttons: amber/yellow, small monospace ─────────────────
    _fk_all_labels = [lbl for lbl, _ in fkeys]
    _fk_labels_js  = str(_fk_all_labels).replace("'", '"')
    st.components.v1.html(f"""
<script>
(function() {{
  const allFkLabels = {_fk_labels_js};
  function styleFkeyButtons() {{
    const btns = window.parent.document.querySelectorAll('button');
    btns.forEach(btn => {{
      const txt = btn.innerText.trim();
      if (allFkLabels.includes(txt)) {{
        btn.style.fontSize      = '9px';
        btn.style.padding       = '2px 2px';
        btn.style.minHeight     = '0';
        btn.style.height        = '20px';
        btn.style.lineHeight    = '1';
        btn.style.fontFamily    = 'monospace';
        btn.style.fontWeight    = '700';
        btn.style.letterSpacing = '0.8px';
        btn.style.borderRadius  = '3px';
        btn.style.color         = '#ffb300';
        btn.style.background    = '#0d1326';
        btn.style.border        = '1px solid #ffb30055';
        btn.style.textTransform = 'uppercase';
      }}
      if (allFkLabels.includes(txt)) {{
        btn.addEventListener('mouseenter', function() {{
          this.style.background = '#1a2744';
          this.style.border     = '1px solid #ffb300';
          this.style.color      = '#fff8e1';
        }}, {{once: false}});
        btn.addEventListener('mouseleave', function() {{
          this.style.background = '#0d1326';
          this.style.border     = '1px solid #ffb30055';
          this.style.color      = '#ffb300';
        }}, {{once: false}});
      }}
    }});
  }}
  setTimeout(styleFkeyButtons, 200);
  setTimeout(styleFkeyButtons, 700);
  setTimeout(styleFkeyButtons, 1500);
  const obs = new MutationObserver(styleFkeyButtons);
  obs.observe(window.parent.document.body, {{ childList: true, subtree: true }});
}})();
</script>
""", height=0)

    # ── API key settings ───────────────────────────────────────────────────
    with st.expander("🔑  API Keys — click to expand and enter keys"):
        k = ss.term_api_keys

        # ── Row 1: News (highlighted) ──────────────────────────────────────
        st.markdown("**📰 News**")
        na1, na2 = st.columns([2, 5])
        k['newsapi_key'] = na1.text_input(
            "NewsAPI Key  *(primary news source)*",
            k.get('newsapi_key', ''),
            type="password",
            key="ak_news",
            placeholder="e.g. a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4",
            help="Free key from newsapi.org — powers NEWS command and AI Chat news queries",
        )
        na2.markdown(
            f"<div style='padding-top:28px;font-family:monospace;font-size:12px;"
            f"color:{T['muted']}'>"
            f"🌐 Get a free key at "
            f"<a href='https://newsapi.org/register' target='_blank' "
            f"style='color:{T['blue']}'>newsapi.org/register</a> — no credit card needed. "
            f"Enables: <code>NEWS</code> · <code>NEWS MACRO</code> · <code>NEWS TECH</code> · "
            f"<code>AAPL NEWS</code> · AI Chat news queries."
            f"</div>",
            unsafe_allow_html=True,
        )

        st.markdown("---")

        # ── Row 2: Market data sources ────────────────────────────────────
        st.markdown("**📊 Market Data**")
        mc1, mc2, mc3, mc4 = st.columns(4)
        k['alpha_vantage']  = mc1.text_input("Alpha Vantage", k.get('alpha_vantage',''),
                                              type="password", key="ak_av")
        k['fmp']            = mc2.text_input("FMP",           k.get('fmp',''),
                                              type="password", key="ak_fmp")
        k['fred']           = mc3.text_input("FRED",          k.get('fred',''),
                                              type="password", key="ak_fred")
        k['polygon']        = mc4.text_input("Polygon.io",    k.get('polygon',''),
                                              type="password", key="ak_poly")

        st.markdown("---")

        # ── Row 2b: Additional Sources ─────────────────────────────────────
        st.markdown("**🔍 Additional Sources (free tiers)**")
        ac1b, ac2b, ac3b = st.columns(3)
        k['finnhub'] = ac1b.text_input("Finnhub Key", k.get('finnhub', ''),
                                       type="password", key="ak_finnhub",
                                       placeholder="Free key from finnhub.io",
                                       help="Free key from finnhub.io — enables news & financials fallback")

        st.markdown("---")

        # ── Row 3: AI + Trading ───────────────────────────────────────────
        st.markdown("**🤖 AI Chat & Trading**")
        ac1, ac2, ac3 = st.columns(3)
        k['openai_key'] = ac1.text_input("Remote LLM — API Key", k.get('openai_key', ''),
                                          type="password", key="ak_or",
                                          placeholder="sk-...",
                                          help="API key for your OpenAI-compatible remote service.")
        k['openai_url'] = ac2.text_input("Remote LLM — Base URL", k.get('openai_url', ''),
                                          key="ak_openai_url",
                                          placeholder="http://your-service/v1",
                                          help="Base URL of your remote service (e.g. http://host/v1). Used as the default in AI Chat.")
        k['openai_model'] = ac3.text_input("Remote LLM — Default Model", k.get('openai_model', ''),
                                            key="ak_openai_model",
                                            placeholder="e.g. gpt-4o, mistral-large",
                                            help="Default model name to pre-select in AI Chat.")
        k['alpaca_key']    = ac1.text_input("Alpaca Key",    k.get('alpaca_key', ''),
                                             type="password", key="ak_alpk")
        k['alpaca_secret'] = ac2.text_input("Alpaca Secret", k.get('alpaca_secret', ''),
                                             type="password", key="ak_alps")

        st.markdown("---")

        # ── Row 4: Gmail ──────────────────────────────────────────────────
        st.markdown("**✉️ Gmail SMTP** — enables real email delivery from MSG")
        gc1, gc2 = st.columns(2)
        k['gmail_user'] = gc1.text_input("Gmail Address",      k.get('gmail_user',''),
                                          placeholder="you@gmail.com", key="ak_guser")
        k['gmail_pass'] = gc2.text_input("Gmail App Password", k.get('gmail_pass',''),
                                          type="password",
                                          placeholder="16-char app password",
                                          key="ak_gpass")
        ss.term_api_keys = k

        save_col, msg_col = st.columns([1, 4])
        with save_col:
            if st.button("💾  Save Keys", key="btn_save_api_keys", use_container_width=True):
                if ss.get('user_id'):
                    ok, msg = save_user_api_keys(ss.user_id, k)
                    if ok:
                        msg_col.success("✅ Keys saved to your account")
                    else:
                        msg_col.error(f"Save failed: {msg}")
                else:
                    msg_col.warning("Not logged in — keys are session-only")

        st.caption(
            "🔗 Free keys: [Alpha Vantage](https://www.alphavantage.co/support/#api-key) · "
            "[FMP](https://financialmodelingprep.com/developer/docs) · "
            "[FRED](https://fred.stlouisfed.org/docs/api/api_key.html) · "
            "[Polygon.io](https://polygon.io) · "
            "[NewsAPI](https://newsapi.org/register) · "
            "Remote LLM: enter your service URL and API key in AI Chat sidebar · "
            "[Alpaca](https://alpaca.markets)  |  "
            "Gmail: generate an **App Password** at "
            "[myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords) "
            "(requires 2FA on your Google account)"
        )

    # ── Execute command ────────────────────────────────────────────────────
    # Only run when form is explicitly submitted (Enter or ▶ Run click).
    # Fkey buttons set _should_run=True themselves before rerun.
    if run and cmd_input:
        ss['_should_run'] = True
        ss.term_cmd       = cmd_input
        ss['_cmd_val']    = cmd_input
        if cmd_input.upper() not in [h.upper() for h in ss.term_history[-5:]]:
            ss.term_history.append(cmd_input)
        if len(ss.term_history) > 50: ss.term_history = ss.term_history[-50:]

    should_run = ss.get('_should_run', False)
    active_cmd = ss.term_cmd

    st.markdown("---")

    # ── Command history ────────────────────────────────────────────────────
    if ss.term_history:
        hist_html = '  '.join(
            f'<span class="term-cmd-hist" style="cursor:pointer">› {h}</span>'
            for h in reversed(ss.term_history[-8:]))
        mu = T['muted']
        st.markdown(f"<div style='font-family:monospace;font-size:11px;color:{mu}'>"
                    f"Recent: {hist_html}</div>", unsafe_allow_html=True)

    # ── Main output area ───────────────────────────────────────────────────
    # Commands with internal buttons (SCREEN, SEARCH, IV) must render on every
    # rerun while they're active — not just when _should_run fires.
    cmd_upper_active = active_cmd.strip().upper() if active_cmd else ''

    if cmd_upper_active == 'SCREEN':
        ss['_should_run'] = False
        if _YF_OK:
            try:
                cmd_screen(ss.term_api_keys)
                _source_badge([{'name': 'yfinance', 'url': 'https://pypi.org/project/yfinance/', 'key_used': False}])
            except Exception as e:
                st.error(f"Command error: {e}"); st.exception(e)
        else:
            st.error("⚠️ `yfinance` not installed.")

    elif cmd_upper_active.startswith('SEARCH'):
        ss['_should_run'] = False
        query = active_cmd.strip()[6:].strip()
        try:
            _cmd_search(query)
        except Exception as e:
            st.error(f"Command error: {e}"); st.exception(e)

    elif cmd_upper_active.startswith('IV'):
        ss['_should_run'] = False
        try:
            iv_parts = active_cmd.strip().upper().split()
            cmd_polygon_iv(iv_parts, ss.term_api_keys)
            _source_badge([
                {'name': 'Polygon.io', 'url': 'https://polygon.io',
                 'key_used': bool(ss.term_api_keys.get('polygon'))},
                {'name': 'yfinance',   'url': 'https://pypi.org/project/yfinance/',
                 'key_used': False},
            ])
        except Exception as e:
            st.error(f"Command error: {e}"); st.exception(e)

    elif should_run and active_cmd:
        ss['_should_run'] = False   # consume the flag — never re-fires on next rerun
        if not _YF_OK:
            st.error("⚠️ `yfinance` is not installed. Run `pip install yfinance` and restart.")
            return
        try:
            with st.spinner(f"Executing: {active_cmd.upper()}…"):
                parse_and_run_command(active_cmd, ss.term_api_keys)
        except Exception as e:
            st.error(f"Command error: {e}")
            st.exception(e)

        # ── PDF Export button ──────────────────────────────────────────────
        st.markdown("---")
        exp_col, _ = st.columns([1, 4])
        with exp_col:
            if st.button("⬇️ Export as PDF", key="pdf_export_btn",
                         help="Download this terminal output as a PDF report"):
                try:
                    user_email = st.session_state.get('user_email', '')
                    cmd_upper  = active_cmd.upper().strip()
                    parts_pdf  = cmd_upper.split()
                    ticker_pdf = parts_pdf[1] if len(parts_pdf) > 1 else ''
                    subtitle   = f"Command: {cmd_upper}"
                    if ticker_pdf:
                        subtitle += f"  |  Ticker: {ticker_pdf}"

                    # Build a minimal-but-useful single-page summary
                    sections = [
                        {'type': 'text',
                         'text': (f"Terminal command <b>{cmd_upper}</b> executed at "
                                  f"{__import__('datetime').datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}."
                                  f" See full interactive output in the Strategy Analyzer terminal.")},
                        {'type': 'divider'},
                    ]

                    # Enrich with live data depending on command
                    try:
                        import yfinance as _yf
                        import math as _math
                        cmd0_pdf = parts_pdf[0]

                        if ticker_pdf and cmd0_pdf in ('OV', 'DES', 'VOL', 'FA',
                                                        'CHART', 'DIV', 'OPT'):
                            info = _yf.Ticker(ticker_pdf).info
                            fi   = _yf.Ticker(ticker_pdf).fast_info
                            last = getattr(fi, 'last_price', None) or getattr(fi, 'previous_close', None)
                            prev = getattr(fi, 'previous_close', None)
                            chg_p = ((float(last)-float(prev))/float(prev)*100
                                     if last and prev and float(prev) > 0 else None)

                            sections.append({'type': 'heading', 'level': 2,
                                             'text': info.get('shortName', ticker_pdf)})
                            sections.append({'type': 'metrics', 'items': [
                                {'label': 'Price',
                                 'value': f"${float(last):,.4f}" if last else '—',
                                 'delta': f"{chg_p:+.2f}%" if chg_p else None},
                                {'label': 'Market Cap',
                                 'value': _fmt_large_pdf(info.get('marketCap'))},
                                {'label': 'P/E Ratio',
                                 'value': f"{info.get('trailingPE', '—'):.2f}"
                                          if isinstance(info.get('trailingPE'), float) else '—'},
                                {'label': '52W High',
                                 'value': f"${info.get('fiftyTwoWeekHigh','—')}"},
                                {'label': '52W Low',
                                 'value': f"${info.get('fiftyTwoWeekLow','—')}"},
                                {'label': 'Sector',
                                 'value': info.get('sector','—')},
                            ]})

                            # 1-year price chart
                            df_ch = _yf.Ticker(ticker_pdf).history(
                                period='1y', interval='1d', auto_adjust=True)
                            if not df_ch.empty:
                                import plotly.graph_objects as _go
                                _T = {'bg':'#0a0e1a','panel':'#0d1326','border':'#1e3a5f',
                                      'amber':'#ffb300','green':'#00e676','red':'#ff1744',
                                      'white':'#e0e0e0'}
                                fig_ch = _go.Figure(go.Candlestick(
                                    x=df_ch.index,
                                    open=df_ch['Open'], high=df_ch['High'],
                                    low=df_ch['Low'],   close=df_ch['Close'],
                                    name=ticker_pdf,
                                    increasing_line_color=_T['green'],
                                    decreasing_line_color=_T['red'],
                                ))
                                fig_ch.update_layout(
                                    title=f'{ticker_pdf} — 1 Year',
                                    paper_bgcolor=_T['bg'], plot_bgcolor=_T['panel'],
                                    font=dict(color=_T['white'], family='monospace'),
                                    height=380, xaxis_rangeslider_visible=False,
                                    margin=dict(l=10,r=10,t=45,b=10))
                                sections.append({'type': 'plotly_fig', 'fig': fig_ch,
                                                 'caption': f'{ticker_pdf} 1-year daily candlestick',
                                                 'height': 380})

                            # Business summary
                            summary = info.get('longBusinessSummary', '')
                            if summary:
                                sections.append({'type': 'heading', 'level': 2, 'text': 'Business Summary'})
                                sections.append({'type': 'text', 'text': summary[:1200] +
                                                 ('…' if len(summary) > 1200 else '')})

                        elif cmd0_pdf == 'WL':
                            from database import wl_get
                            items = wl_get(st.session_state.get('user_id', 0))
                            if items:
                                rows = []
                                for item in items:
                                    fi2  = _yf.Ticker(item['ticker']).fast_info
                                    last2 = getattr(fi2,'last_price',None) or getattr(fi2,'previous_close',None)
                                    prev2 = getattr(fi2,'previous_close',None)
                                    chg2  = ((float(last2)-float(prev2))/float(prev2)*100
                                             if last2 and prev2 and float(prev2) > 0 else None)
                                    rows.append({
                                        'Ticker': item['ticker'],
                                        'Label':  item['label'] or '—',
                                        'Price':  f"${float(last2):,.4f}" if last2 else '—',
                                        'Day Chg%': f"{chg2:+.2f}%" if chg2 else '—',
                                    })
                                sections.append({'type': 'heading', 'level': 2, 'text': 'Watchlist'})
                                sections.append({'type': 'dataframe', 'df': pd.DataFrame(rows)})

                        elif cmd0_pdf == 'PNL':
                            from database import pnl_get
                            positions = pnl_get(st.session_state.get('user_id', 0))
                            if positions:
                                rows = []
                                for pos in positions:
                                    fi2  = _yf.Ticker(pos['ticker']).fast_info
                                    last2= getattr(fi2,'last_price',None) or getattr(fi2,'previous_close',None)
                                    qty  = pos['quantity']; cost = pos['cost_basis']
                                    if last2:
                                        mv   = float(last2) * qty
                                        pnl  = mv - cost * qty
                                        pnlp = (float(last2) - cost) / cost * 100
                                        rows.append({'Ticker': pos['ticker'],
                                            'Qty': qty, 'Cost': f"${cost:.2f}",
                                            'Price': f"${float(last2):.4f}",
                                            'Mkt Val': f"${mv:,.2f}",
                                            'P&L': f"${pnl:+,.2f}",
                                            'P&L %': f"{pnlp:+.2f}%"})
                                    else:
                                        rows.append({'Ticker': pos['ticker'],
                                            'Qty': qty, 'Cost': f"${cost:.2f}",
                                            'Price': '—', 'Mkt Val': '—',
                                            'P&L': '—', 'P&L %': '—'})
                                sections.append({'type': 'heading', 'level': 2, 'text': 'Portfolio Positions'})
                                sections.append({'type': 'dataframe', 'df': pd.DataFrame(rows)})

                    except Exception as enrich_err:
                        sections.append({'type': 'text',
                                         'text': f'(Data enrichment unavailable: {enrich_err})'})

                    pdf_bytes = generate_terminal_pdf(
                        title=f"Terminal: {cmd_upper}",
                        sections=sections,
                        user_email=user_email,
                        subtitle=subtitle,
                    )
                    st.download_button(
                        label="📄 Download PDF",
                        data=pdf_bytes,
                        file_name=f"terminal_{cmd_upper.replace(' ','_')}"
                                  f"_{__import__('datetime').datetime.utcnow().strftime('%Y%m%d_%H%M')}.pdf",
                        mime="application/pdf",
                        key="pdf_dl_btn",
                    )
                    st.success("✅ PDF ready — click Download PDF above.")
                except Exception as pdf_err:
                    st.error(f"PDF export failed: {pdf_err}")
                    st.caption("Tip: ensure `reportlab` and `kaleido` are installed — "
                               "`pip install reportlab kaleido`")
    else:
        # Default landing: market overview
        st.markdown(f"<div class='term-header'>📡  MARKET OVERVIEW</div>", unsafe_allow_html=True)
        st.caption("Type a command above or click a function key. Type **HELP** for full command reference.")
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown("**Equity Indices**")
            for name, sym in WORLD_INDICES[:6]:
                df = _yf_history(sym, period='2d')
                if df.empty or len(df) < 2: continue
                prev, last = float(df['Close'].iloc[-2]), float(df['Close'].iloc[-1])
                chg_p = (last-prev)/prev*100
                color = T['green'] if chg_p >= 0 else T['red']
                arrow = '▲' if chg_p >= 0 else '▼'
                st.markdown(
                    f"<span class='term-lbl'>{name:15s}</span> "
                    f"<span class='term-neu'>{last:>12,.2f}</span>  "
                    f"<span style='color:{color};font-family:monospace'>{arrow}{chg_p:+.2f}%</span>",
                    unsafe_allow_html=True)
        with col_b:
            st.markdown("**FX & Rates**")
            for name, sym in FX_PAIRS[:4]:
                df = _yf_history(sym, period='2d')
                if df.empty or len(df) < 2: continue
                prev, last = float(df['Close'].iloc[-2]), float(df['Close'].iloc[-1])
                chg_p = (last-prev)/prev*100
                color = T['green'] if chg_p >= 0 else T['red']
                arrow = '▲' if chg_p >= 0 else '▼'
                st.markdown(
                    f"<span class='term-lbl'>{name:10s}</span> "
                    f"<span class='term-neu'>{last:>10.5f}</span>  "
                    f"<span style='color:{color};font-family:monospace'>{arrow}{chg_p:+.3f}%</span>",
                    unsafe_allow_html=True)
            for name, sym in CRYPTO_PAIRS[:3]:
                df = _yf_history(sym, period='2d')
                if df.empty or len(df) < 2: continue
                prev, last = float(df['Close'].iloc[-2]), float(df['Close'].iloc[-1])
                chg_p = (last-prev)/prev*100
                color = T['green'] if chg_p >= 0 else T['red']
                arrow = '▲' if chg_p >= 0 else '▼'
                st.markdown(
                    f"<span class='term-lbl'>{name:10s}</span> "
                    f"<span class='term-neu'>{last:>12,.2f}</span>  "
                    f"<span style='color:{color};font-family:monospace'>{arrow}{chg_p:+.2f}%</span>",
                    unsafe_allow_html=True)