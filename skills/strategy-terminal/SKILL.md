---
name: Strategy Terminal
description: Explicit-invocation only. Load this when the user types /st, runs a Strategy Terminal command, or names this skill. Do not auto-load it for generic market or quote questions — use the st.run tool or /st instead.
metadata:
  # Hidden from the model's auto-invoke list: the skill is reachable only when a
  # command (/st) or the user names it. Remove this to restore auto-selection.
  opencode/autoinvoke: false
---

# Strategy Terminal — command skill

The StrategyTerminal engine (`app-cli.py`) is bundled with this skill. Every number you quote must
come from a command you actually ran — never from memory, and never estimated.

## 0. Always run a command first

Invocation boundary: this protocol applies to the invocation that loaded it (the `/st` command or
an explicit request). In later chat messages, run the engine only when the user asks for data or
types another `/st` — a bare `help`, `wei`, or lone ticker is conversation first; ask instead of
assuming.

| Need | Command |
|---|---|
| quote / overview | `"$ST" AAPL` |
| price chart | `"$ST" "AAPL GP 6mo"` |
| market / macro / news | `"$ST" WEI` · `"$ST" ECON` · `"$ST" NEWS` |
| every available command | `"$ST" --list-commands` · `"$ST" HELP` |

If this session **also** has the `st.run` / `st.commands` tools (the OpenCode plugin registers
them), prefer the tools — same engine, and charts come back as inline attachments. Every other
host (Claude Code, Codex, Cursor, a plain shell) uses the CLI, which needs nothing beyond Python.

### Running it

Your host reports this skill's **base directory** — the folder holding this `SKILL.md`. Define it
once per session:

```bash
# The skill loader reports the base directory; these are the install defaults.
CONFIG_ROOT="${XDG_CONFIG_HOME:-$HOME/.config}"
SKILL_DIR="${SKILL_DIR:-$CONFIG_ROOT/opencode/skills/strategy-terminal}"
ST="$SKILL_DIR/scripts/st"
"$ST" --list-commands | head
```

`~/.claude/skills/strategy-terminal` (Claude Code) and `~/.codex/skills/strategy-terminal`
(Codex) hold the same two files with this path already rewritten, so the block above works as-is
if you export `SKILL_DIR` to whichever folder the host loaded.

The runner finds the engine in this order: `$ST_CLI_APP_DIR` → this package's `engine/` →
the host-neutral copy (`~/.config/strategy-terminal`, used by Claude Code and Codex) → the
OpenCode copy (`~/.config/opencode/strategy-terminal`) → the checkout's `app-cli/` →
`~/Apps/StrategyTerminal`.
It picks Python from `$ST_CLI_PYTHON`, else `<app>/venv/bin/python`, `<app>/.venv/bin/python`,
`~/venv/bin/python`, else `python3`.

Requirements: `numpy pandas matplotlib plotly requests scipy scikit-learn reportlab pymupdf
kaleido yfinance feedparser` (plus `plotly_get_chrome -y` for PNG charts). Missing modules show
up as `ModuleNotFoundError` — point `ST_CLI_PYTHON` at an interpreter that has them.

## 1. Command families

| Family | Examples | Returns |
|---|---|---|
| Ticker | `AAPL`, `AAPL GP 1y`, `AAPL DES`, `AAPL FA`, `AAPL NEWS`, `AAPL OPT`, `AAPL DVD` | overview, chart, description, financials, headlines, option chain, dividends |
| Compare | `AAPL COMP MSFT GOOGL` | side-by-side fundamentals |
| Market | `WEI`, `MOVERS GAINERS`, `FX`, `CRYPTO`, `CRYPTO TOP`, `COIN bitcoin`, `RATES`, `CMDTY`, `SECTOR`, `IND SPX`, `TOP` | global tape |
| Volatility | `VOL`, `VOL TSLA 6mo`, `IV AAPL`, `IV NVDA 1y` | VIX, realised vs implied vol, term structure, skew, Greeks |
| Macro | `ECON`, `ECON GDP`, `ECON CPI`, `ECON SPREAD`, `FRED CPIAUCSL`, `ECON GLOBAL` | FRED series, global comparison |
| Credit | `OAS`, `OAS HY`, `OASD 1-3Y` | spread dashboard, spread by maturity |
| News | `NEWS`, `NEWS TECH`, `NEWS FEED`, `NEWS SENTIMENT`, `SENTIMENT AAPL` | headlines, RSS aggregation, GDELT tone |
| Research | `EARN AAPL`, `ANR TSLA`, `RV AAPL`, `SHORT GME`, `INSIDER AAPL`, `IPO`, `ECAL` | earnings, ratings, relative value, short interest, insiders, calendar |
| Risk / returns | `RISK AAPL`, `TRA AAPL SPY 5y`, `CORR AAPL MSFT 6mo` | beta/alpha/VaR, total return vs benchmark, correlation |
| Screen / search | `SCREEN`, `SEARCH apple`, `SEARCH TSLA` | screener, ticker lookup |
| Account | `WL`, `WL ADD TSLA Tech`, `PNL`, `PNL ADD AAPL 100 150`, `PORT`, `LIST ALERT`, `AAPL ADD_ALERT EVERY 2%` | watchlist, P&L, portfolio, alerts |
| Meta | `HELP`, `--list-commands` | full reference |

Conventions that trip people up:

- **Charts** need a range token: `AAPL GP` defaults to 1y; `1d`, `5d`, `1mo`, `3mo`, `6mo`, `1y`, `5y` also work.
- **Account commands** (`WL`, `PNL`, `PORT`, alerts) need a local account: add `--user-id N` or
  `--email you@example.com`. Everything else runs anonymously by default.
- Analysis commands take a lookback as the last token: `VOL NVDA 6mo`, `CORR SPY QQQ IWM 1y`.
- Symbols are Yahoo-style: `AAPL`, `^GSPC`, `BTC-USD` where relevant; `COIN bitcoin` for CoinGecko names.

## 2. Flags

| Flag | Effect |
|---|---|
| `--show` | build a report, open the PDF in the browser, and return its pages as PNGs |
| `--open-pdf` | open the PDF (implied by `--show`) |
| `--no-open-pdf` | build the PDF and page images but keep the browser closed |
| `--open-images` | open each exported chart PNG in the default browser (default) |
| `--no-open-images` | do not launch the browser for chart PNGs |
| `--user-id N` / `--email X` | act as a local account instead of anonymous |
| `--no-images` | text only, no PNG export |
| `--max-rows N` | limit table rows |
| `--list-commands` | dump all ~140 commands |

Any other `app-cli.py` flag passes straight through. The plugin's tools take the same options as
`user`, `images`, `open_images`, `show`, `open_pdf`, `max_rows` arguments instead of flags.

## 3. Presenting the output

- Lead with the key numbers (price, change, level, spread) before any commentary.
- Keep the tables the engine prints; do not re-typeset numbers.
- For every `![...](/abs/path/chart.png)` line, call the `read` tool on that absolute path so the
  chart renders inline. In tool mode the images arrive as attachments already.
- Say which command and range produced a figure when the user may want to reproduce it.
- Never fill gaps with estimates. If a source is rate-limited or a key is missing, report the gap
  and name the optional `keys.json` entry that would fix it.
- Charts and PDFs land in `<app>/cli_out/<timestamp>/<command>/` — quote the paths, they are safe
  to delete. Exported charts (and PDFs, when `--show` is used) also pop in the default browser,
  one tab per file up to 10 per command; `--no-open-images` / `open_images: false` keeps it closed.

## 4. Troubleshooting

| Symptom | Fix |
|---|---|
| `app-cli.py folder not found` | reinstall, or set `ST_CLI_APP_DIR` to the folder holding `app-cli.py` |
| `ModuleNotFoundError` | `ST_CLI_PYTHON` → interpreter with the deps; or `pip install -r` the list in §0 |
| chart missing / `chart not rendered as image` | install `kaleido`, run `plotly_get_chrome -y` |
| `--show` opened nothing | headless session: the PDF and page PNGs are still written; use `--no-open-pdf` |
| command hangs | it is fetching many tickers; raise `ST_CLI_TIMEOUT_MS` (tools) or rerun with a narrower ticker list |
| account command returns anonymous data | add `--user-id N` / `--email X` |

## 5. Configuration and local data

- API keys are **optional**. `app-cli.py` reads them from, in order:
  1. the local account database (`users.db` in the engine folder),
  2. an explicit `--keys-file PATH`,
  3. the default `<config-root>/strategy-terminal/keys.json`, when present.
  It never reads API keys, passwords or tokens from environment variables. Never ask the user
  to paste a key into the chat.
- Keys file format is a flat JSON object keyed by service:
  `{"fred": "...", "fmp": "...", "alpha_vantage": "...", "polygon": "...", "newsapi_key": "...", "finnhub": "...", "alpaca_key": "...", "alpaca_secret": "..."}`.
  Every entry is optional; keyless sources (yfinance, CoinGecko, GDELT, RSS, World Bank) work
  with no file at all.
- Files read: the bundled `engine/` folder and its modules, the optional `users.db` and keys
  file, and an explicit `--keys-file`.
- Files written: `users.db` (schema initialisation only) and generated artefacts under
  `engine/cli_out/<timestamp>/<command>/` (PNG, CSV, PDF, Markdown). No credentials or account
  selections are cached on disk.
- The runner reads only `ST_CLI_APP_DIR`, `ST_CLI_PYTHON`, `OPENCODE_CONFIG_DIR` and
  `XDG_CONFIG_HOME` to locate the engine and a Python interpreter. None of these carry secrets.

## 6. Network access

All requests are read-only market-data or news lookups. The skill uploads no files, account
data, keys or chat content. A configured API key is sent only to the service it belongs to.

| Host(s) | Purpose | Key needed |
|---|---|---|
| `query1.finance.yahoo.com`, `query2.finance.yahoo.com`, `finance.yahoo.com`, `fc.yahoo.com`, `guce.yahoo.com` | quotes, history, options, search, Yahoo news (yfinance) | no |
| `fred.stlouisfed.org`, `api.stlouisfed.org` | FRED macro series | no (optional FRED key) |
| `www.alphavantage.co` | news sentiment, technical fallback | optional |
| `financialmodelingprep.com` | fundamentals, profiles, calendars | optional |
| `newsapi.org` | headline search | optional |
| `finnhub.io` | company/market news | optional |
| `data.alpaca.markets` | historical bars | optional |
| `api.polygon.io` | options and implied volatility | optional |
| `api.coingecko.com` | crypto quotes and market tables | no |
| `api.gdeltproject.org` | news tone / sentiment | no |
| `api.worldbank.org` | global macro comparison | no |
| `feeds.content.dowjones.io` (MarketWatch) | RSS headlines | no |
| `www.investopedia.com` | RSS headlines | no |
| `feeds.bloomberg.com` | RSS headlines | no |
| `www.cnbc.com` | RSS headlines | no |
| `www.zerohedge.com` | RSS headlines | no |
| `seekingalpha.com` | RSS headlines | no |
| `feeds.npr.org` | RSS headlines | no |
| `rss.nytimes.com` | RSS headlines | no |
| `feeds.bbci.co.uk` | RSS headlines | no |
| `www.wsj.com` | RSS headlines | no |
| `www.economist.com` | RSS headlines | no |

There are no other outbound calls: no telemetry, analytics, update checks, LLM/chat endpoints,
local daemons, or arbitrary user-supplied URLs. Documentation links printed in tables are not
contacted.

## 7. Boundaries

- The engine is read-only market data. It does not place orders, move money or send mail.
- Price-**alert emails** are only sent by the StrategyTerminal Streamlit app; the CLI and this
  skill just manage the alert list.
- Not investment advice: report data and mechanisms, do not instruct trades.
