---
name: Strategy Terminal
description: Pull live market data from the StrategyTerminal engine (scripts/st) — ticker overviews and price charts, movers, FX, crypto, rates, commodities, sectors, indices, volatility/IV, options, credit spreads, macro (FRED/World Bank), news and sentiment, earnings, analyst ratings, short interest, insider trades, correlations, risk/returns, screener, watchlist and P&L. Use whenever the user asks for a quote, chart, market or macro read, news headlines, or portfolio numbers.
metadata:
  opencode/autoinvoke: true
---

# Strategy Terminal — command skill

The StrategyTerminal engine (`app-cli.py`) is bundled with this skill. Every number you quote must
come from a command you actually ran — never from memory, and never estimated.

## 0. Always run a command first

| Need | Command |
|---|---|
| quote / overview | `"$ST" AAPL` |
| price chart | `"$ST" "AAPL GP 6mo"` |
| market / macro / news | `"$ST" WEI` · `"$ST" ECON` · `"$ST" NEWS` |
| every available command | `"$ST" --list-commands` · `"$ST" HELP` |

If this session **also** has the `st.run` / `st.commands` tools (the optional plugin registers
them), prefer the tools — same engine, and charts come back as inline attachments. Otherwise use
the CLI, which is dependency-free beyond Python.

### Running it

The `skill` tool reports this skill's **base directory**. Define it once per session:

```bash
SKILL_DIR="${SKILL_DIR:-$HOME/.config/opencode/skills/strategy-terminal}"
ST="$SKILL_DIR/scripts/st"
"$ST" --list-commands | head
```

The runner finds the engine in this order: `$ST_CLI_APP_DIR` → the installer's bundled
`~/.config/opencode/strategy-terminal` → the checkout's `app-cli/` → `~/Apps/StrategyTerminal`.
It picks Python from `$ST_CLI_PYTHON`, else `<app>/venv/bin/python`, `<app>/.venv/bin/python`,
`~/venv/bin/python`, else `python3`.

Requirements: `numpy pandas plotly requests scipy scikit-learn reportlab pymupdf kaleido
yfinance` (plus `plotly_get_chrome -y` for PNG charts). Missing modules show up as
`ModuleNotFoundError` — point `ST_CLI_PYTHON` at an interpreter that has them.

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
| `--user-id N` / `--email X` | act as a local account instead of anonymous |
| `--no-images` | text only, no PNG export |
| `--max-rows N` | limit table rows |
| `--list-commands` | dump all ~140 commands |

Any other `app-cli.py` flag passes straight through. The plugin's tools take the same options as
`user`, `images`, `show`, `open_pdf`, `max_rows` arguments instead of flags.

## 3. Presenting the output

- Lead with the key numbers (price, change, level, spread) before any commentary.
- Keep the tables the engine prints; do not re-typeset numbers.
- For every `![...](/abs/path/chart.png)` line, call the `read` tool on that absolute path so the
  chart renders inline. In tool mode the images arrive as attachments already.
- Say which command and range produced a figure when the user may want to reproduce it.
- Never fill gaps with estimates. If a source is rate-limited or a key is missing, report the gap
  and name the env var that would fix it.
- Charts and PDFs land in `<app>/cli_out/<timestamp>/<command>/` — quote the paths, they are safe
  to delete.

## 4. Troubleshooting

| Symptom | Fix |
|---|---|
| `app-cli.py folder not found` | reinstall, or set `ST_CLI_APP_DIR` to the folder holding `app-cli.py` |
| `ModuleNotFoundError` | `ST_CLI_PYTHON` → interpreter with the deps; or `pip install -r` the list in §0 |
| chart missing / `chart not rendered as image` | install `kaleido`, run `plotly_get_chrome -y` |
| `--show` opened nothing | headless session: the PDF and page PNGs are still written; use `--no-open-pdf` |
| command hangs | it is fetching many tickers; raise `ST_CLI_TIMEOUT_MS` (tools) or rerun with a narrower ticker list |
| account command returns anonymous data | add `--user-id N` / `--email X` |

## 5. Boundaries

- The engine is read-only market data. It does not place orders, move money or send mail.
- Price-**alert emails** are only sent by the StrategyTerminal Streamlit app; the CLI and this
  skill just manage the alert list.
- API keys are optional and read from the environment by `app-cli.py` only
  (`FRED_API_KEY`, `FMP_API_KEY`, `ALPHA_VANTAGE_API_KEY`, `POLYGON_API_KEY`, `NEWSAPI_KEY`,
  `FINNHUB_API_KEY`, `OPENROUTER_API_KEY`). Never ask the user to paste keys into the chat.
- Not investment advice: report data and mechanisms, do not instruct trades.
