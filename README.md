# Strategy Terminal plugin for OpenCode

Market data, technicals, macro, news and risk commands from the
**StrategyTerminal** app, available inside OpenCode as tools, as a `/st`
slash command, and as a **self-contained skill** that needs no plugin.

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
| `skills/strategy-terminal/` | The skill: `SKILL.md` + `scripts/st` runner (works without the plugin) |
| `commands/st.md` | The `/st <args>` slash command |
| `bin/st.sh` | Shim the slash command runs; forwards to the skill's runner |
| `app-cli/` | **Self-contained** command engine (`app-cli.py` plus the `terminal`, `features`, `config`, `database`, `chat`, `rag` and `terminal_pdf` modules) |
| `install.sh` | Installs any subset: plugin, skill, or both (plus `/st`) |

## Requirements

- Python 3 with the engine's dependencies:
  `numpy pandas plotly requests scipy scikit-learn reportlab pymupdf kaleido`
  (and `yfinance` for market data).
- Optional, for PNG chart export: `kaleido` plus a Chrome build
  (`plotly_get_chrome -y` installs one).

No separate StrategyTerminal checkout is needed — `app-cli/` is bundled.

## Install

```bash
./install.sh                 # plugin + skill + engine + /st + bin wrapper (default)
./install.sh --plugin-only   # only the st.* tools + the engine
./install.sh --skill-only    # skill + engine + /st (no plugin)
./install.sh --dry-run       # show what would happen (combine with any mode)
```

| Mode | Installs | `/st` | Tools | Needs |
|---|---|---|---|---|
| default | plugin, skill, engine, command, bin | ✓ | ✓ | python3 + deps |
| `--plugin-only` | plugin, engine | ✗ | ✓ | python3 + deps |
| `--skill-only` | skill, engine, command, bin | ✓ | ✗ | python3 + deps |

The installer places the self-contained engine in
`~/.config/opencode/strategy-terminal/`, so it works without a
`~/Apps/StrategyTerminal` checkout. Both modes share that one engine copy.

Manual install (plugin + `/st`, the old behaviour):

```bash
cp plugins/strategy-terminal.ts ~/.config/opencode/plugins/
cp commands/st.md              ~/.config/opencode/commands/
mkdir -p ~/.config/opencode/bin ~/.config/opencode/strategy-terminal
cp bin/st.sh                   ~/.config/opencode/bin/ && chmod +x ~/.config/opencode/bin/st.sh
cp app-cli/*.py                ~/.config/opencode/strategy-terminal/
```

Restart OpenCode (or wait for the config watcher to reload), then `/st AAPL`.

## Skill (no plugin)

`skills/strategy-terminal/` is a normal OpenCode skill: `SKILL.md` plus
`scripts/st`, a runner with the same flag handling as the plugin. When loaded,
the agent shells out:

```bash
~/.config/opencode/skills/strategy-terminal/scripts/st AAPL GP 6mo
```

Install it alone with `./install.sh --skill-only`, or point a config at the
checkout (the runner also finds `app-cli/` there, so no install is needed):

```jsonc
// ~/.config/opencode/opencode.json
{ "skills": ["/path/to/opencode-strategy-terminal-plugin/skills"] }
```

### Invocation model — explicit only

The skill ships with `metadata.opencode/autoinvoke: false`, so it is **hidden
from the model's auto-invoke list**. It does not fire on generic phrases like
"help", "what's the market doing" or a bare ticker; the two ways in are:

1. **`/st <command>`** — the deterministic, plugin-style entry point (default
   install). The command loads the skill for presentation rules and injects the
   engine output.
2. **Naming it** — "use the strategy-terminal skill" / "load skill
   strategy-terminal". The id is `strategy-terminal`.

If you want the model to be able to select it on its own again, flip the
frontmatter back to `true` and reinstall. To keep auto-selection but require
approval, leave it `true` and add a permission instead:

```jsonc
// ~/.config/opencode/opencode.json
{ "permissions": { "skill": { "strategy-terminal": "ask", "*": "allow" } } }
```

If both plugin and skill are installed, the skill prefers the `st.run` tool and
falls back to `scripts/st`; either way the output is the same engine.

## Configure

Nothing is required after `./install.sh`; the bundled app is used
automatically. If you keep a venv, point at it, or override the app folder:

| Variable | Meaning | Default |
|---|---|---|
| `ST_CLI_APP_DIR` | folder containing `app-cli.py` | bundled `~/.config/opencode/strategy-terminal`, else the checkout's `app-cli/`, else `~/Apps/StrategyTerminal` |
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
| skill not offered to the agent | confirm `~/.config/opencode/skills/strategy-terminal/SKILL.md` exists and has a `description`; skills reload without a restart |
| skill runs but `app-cli.py not found` | set `ST_CLI_APP_DIR`, or re-run `./install.sh --skill-only` to place the bundled engine |
| `--show` did not open a browser | check `DISPLAY`/`WAYLAND_DISPLAY`/`BROWSER`; the PDF is still written next to the PNGs |
| a command hangs | it is fetching many tickers; raise `ST_CLI_TIMEOUT_MS` |

## Uninstall

```bash
# everything
rm ~/.config/opencode/plugins/strategy-terminal.ts \
   ~/.config/opencode/commands/st.md \
   ~/.config/opencode/bin/st.sh
rm -rf ~/.config/opencode/skills/strategy-terminal \
       ~/.config/opencode/strategy-terminal

# or drop just one half
rm ~/.config/opencode/plugins/strategy-terminal.ts            # plugin gone, skill stays
rm -rf ~/.config/opencode/skills/strategy-terminal            # skill gone, plugin stays
```

The engine at `~/.config/opencode/strategy-terminal` is shared, so remove it only
when neither half is needed.

## Notes

- Price-alert **emails** are only sent by the StrategyTerminal Streamlit app
  (it runs the scheduler); the CLI and this plugin just manage alerts.
- Commands that touch watchlist / P&L / portfolio / alerts need a local account
  (`--user-id N`, or log in once through `app-cli.py`).
- **`WEI` session logic** — each index is compared with the previous session on
  *its own* exchange calendar, so Asian and US closes are never paired by
  accident. If yfinance drops a daily bar (`^GSPC` on 2026-10-21, for example)
  the prior close is rebuilt from that symbol's 5-minute bars instead of
  silently spanning two sessions. Futures and the implied open are measured
  from the 16:00 ET cash close, not from the futures' previous settlement,
  so the session's move is not counted twice.
- Verified with OpenCode 1.18.x, which loads local plugins through two shapes;
  the plugin exports both (`setup` and `server`) so it works either way.
