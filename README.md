# Strategy Terminal plugin for OpenCode

Market data, technicals, macro, news and risk commands from the
**StrategyTerminal** app, available inside OpenCode as tools and as a
`/st` slash command.

```
/st AAPL                    overview: price, stats, 1Y chart
/st AAPL GP 6mo             price chart
/st VOL TSLA 6mo --show     volatility dashboard + report in browser + pages as images
/st WEI                     world equity indices
/st NEWS TOP                market headlines
/st --user-id 1 WL          your watchlist (only with a local account)
```

Runs **anonymously by default** — no user id, password or API key required for
the public data sources (yfinance, CoinGecko, GDELT, RSS, World Bank).

---

## Contents

| Path | Purpose |
|---|---|
| `plugins/strategy-terminal.ts` | OpenCode plugin exposing the `st.run` / `st.commands` tools |
| `commands/st.md` | The `/st <args>` slash command |
| `bin/st.sh` | Wrapper the slash command runs |
| `app-cli/` | **Self-contained** command engine (`app-cli.py` plus the `terminal`, `features`, `config`, `database`, `chat`, `rag` and `terminal_pdf` modules) |
| `install.sh` | Copies the plugin and the bundled app into `~/.config/opencode` |

## Requirements

- Python 3 with the engine's dependencies:
  `numpy pandas plotly requests scipy scikit-learn reportlab pymupdf kaleido`
  (and `yfinance` for market data).
- Optional, for PNG chart export: `kaleido` plus a Chrome build
  (`plotly_get_chrome -y` installs one).

No separate StrategyTerminal checkout is needed — `app-cli/` is bundled.

## Install

```bash
./install.sh                 # install plugin + bundled app into ~/.config/opencode
./install.sh --dry-run       # see what it would do
```

The installer places the self-contained engine in
`~/.config/opencode/strategy-terminal/`, so it works without a
`~/Apps/StrategyTerminal` checkout.

Manual install:

```bash
cp plugins/strategy-terminal.ts ~/.config/opencode/plugins/
cp commands/st.md              ~/.config/opencode/commands/
mkdir -p ~/.config/opencode/bin ~/.config/opencode/strategy-terminal
cp bin/st.sh                   ~/.config/opencode/bin/ && chmod +x ~/.config/opencode/bin/st.sh
cp app-cli/*.py                ~/.config/opencode/strategy-terminal/
```

Restart OpenCode (or wait for the config watcher to reload), then `/st AAPL`.

## Configure

Nothing is required after `./install.sh`; the bundled app is used
automatically. If you keep a venv, point at it, or override the app folder:

| Variable | Meaning | Default |
|---|---|---|
| `ST_CLI_APP_DIR` | folder containing `app-cli.py` | bundled `~/.config/opencode/strategy-terminal`, else `~/Apps/StrategyTerminal` |
| `ST_CLI_PYTHON` | interpreter with the app's dependencies | `<app>/venv/bin/python`, `<app>/.venv/bin/python`, `~/venv/bin/python`, `python3` |
| `ST_CLI_SCRIPT` | CLI file name | `app-cli.py` |
| `ST_CLI_TIMEOUT_MS` | per-command timeout | `240000` |
| `OPENCODE_CONFIG_DIR` | OpenCode config location | `~/.config/opencode` |

API keys are **optional** and are read by `app-cli.py` from environment
variables only (nothing is written into this plugin, and the plugin never
passes keys around):

```bash
export FRED_API_KEY=...
export FMP_API_KEY=...
export ALPHA_VANTAGE_API_KEY=...
export POLYGON_API_KEY=...        # enables IV AAPL
export NEWSAPI_KEY=...
export FINNHUB_API_KEY=...
export OPENROUTER_API_KEY=...     # enables the OpenRouter chat provider
```

Sources that need no key at all: yfinance, CoinGecko, GDELT, RSS feeds,
World Bank, plus FRED/Yahoo fallbacks.

## Tools

| Tool | Arguments |
|---|---|
| `st.run` | `command` (required), `user`, `images`, `show`, `open_pdf`, `max_rows` |
| `st.commands` | — lists every command (~140 of them) |

`st.run` returns the rendered output as text and every chart as PNG file
content, so front-ends that render attachments show the charts inline. The text
also lists each PNG path, so any agent can display it with its file reader.

### Flags

| Flag | Effect |
|---|---|
| `--show` | render a report, open the PDF in the browser and return its pages as images |
| `--open-pdf` | open the PDF in the browser (implied by `--show`) |
| `--no-open-pdf` | build the PDF and pages but keep the browser closed |
| `--user-id N` / `--email X` | act as a local account instead of anonymous |
| `--no-images` | text-only output (no PNG export) |
| `--max-rows N` | limit table rows |

Any other `app-cli.py` flag can be passed through in the same way.

## Privacy and secrets

- This bundle contains **no credentials** — no API keys, tokens or passwords.
- `app-cli.py` reads keys from the process environment, and (for local
  accounts) from the app's own SQLite store `users.db`, which is **not** part
  of this bundle.
- Logging in with `--email/--password` successfully caches only
  `{user_id, email}` in `~/.config/strategy-terminal/cli.json`. Delete that
  file to forget the account; `--anonymous` never writes it.
- Generated artefacts (charts, CSVs, PDFs) are written under
  `<app>/cli_out/<timestamp>/<command>/` and can be deleted at any time.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `app-cli.py not found in …` | re-run `./install.sh`, or set `ST_CLI_APP_DIR` to the app folder |
| `ModuleNotFoundError` (numpy/pandas/plotly/reportlab/…) | point `ST_CLI_PYTHON` at an interpreter that has the dependencies listed above |
| charts missing, `chart not rendered as image` | install `kaleido` and run `plotly_get_chrome -y` in that venv |
| plugin not visible in OpenCode | restart OpenCode; check `~/.local/share/opencode/log/opencode.log` for `strategy-terminal` |
| `--show` did not open a browser | check `DISPLAY`/`WAYLAND_DISPLAY`/`BROWSER`; the PDF is still written next to the PNGs |
| a command hangs | it is fetching many tickers; raise `ST_CLI_TIMEOUT_MS` |

## Uninstall

```bash
rm ~/.config/opencode/plugins/strategy-terminal.ts \
   ~/.config/opencode/commands/st.md \
   ~/.config/opencode/bin/st.sh
rm -rf ~/.config/opencode/strategy-terminal
```

## Notes

- Price-alert **emails** are only sent by the StrategyTerminal Streamlit app
  (it runs the scheduler); the CLI and this plugin just manage alerts.
- Commands that touch watchlist / P&L / portfolio / alerts need a local account
  (`--user-id N`, or log in once through `app-cli.py`).
- Verified with OpenCode 1.18.x, which loads local plugins through two shapes;
  the plugin exports both (`setup` and `server`) so it works either way.
