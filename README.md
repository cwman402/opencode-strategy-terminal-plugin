# Strategy Terminal plugin for OpenCode

Market data, technicals, macro, news and risk commands from the
**StrategyTerminal** app, available inside OpenCode as tools, as a `/st`
slash command, and as a **self-contained skill** that needs no plugin.
The same skill also runs in **Claude Code** and **Codex CLI** — see
[Claude Code and Codex CLI](#claude-code-and-codex-cli).

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
| `app-cli/` | **Self-contained** command engine (`app-cli.py` plus the `terminal`, `features`, `config`, `database`, `chat`, `rag`, `news` and `terminal_pdf` modules) |
| `install.sh` | Installs any subset, for OpenCode, Claude Code or Codex (`--claude`, `--codex`, `--all-hosts`), and uninstalls it again |

## Requirements

- Python 3 with the engine's dependencies:
  `numpy pandas plotly requests scipy scikit-learn reportlab pymupdf kaleido`
  (and `yfinance` for market data).
- Optional, for PNG chart export: `kaleido` plus a Chrome build
  (`plotly_get_chrome -y` installs one).

No separate StrategyTerminal checkout is needed — `app-cli/` is bundled.

## Install

```bash
./install.sh                 # OpenCode: plugin + skill + engine + /st + bin wrapper (default)
./install.sh --plugin-only   # only the st.* tools + the engine
./install.sh --skill-only    # skill + engine + /st (no plugin)
./install.sh --claude        # Claude Code: skill + engine
./install.sh --codex         # Codex CLI: skill + /st prompt + AGENTS.md block + engine
./install.sh --all-hosts     # OpenCode (default mode) + Claude Code + Codex
./install.sh --dry-run       # show what would happen (combine with any flag)
./install.sh --uninstall     # remove what the same flags would have installed
```

| Mode | Installs | `/st` | Tools | Needs |
|---|---|---|---|---|
| default | plugin, skill, engine, command, bin | ✓ | ✓ | python3 + deps |
| `--plugin-only` | plugin, engine | ✗ | ✓ | python3 + deps |
| `--skill-only` | skill, engine, command, bin | ✓ | ✗ | python3 + deps |
| `--claude` | skill, engine | ✓ (skills loader) | ✗ | python3 + deps |
| `--codex` | skill, prompt, AGENTS.md block, engine | ✓ (prompt) | ✗ | python3 + deps |

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

## Claude Code and Codex CLI

Nothing about the engine is OpenCode-specific: `app-cli.py` is a plain Python CLI, and the skill
is two files. Two extra install shapes wire it into the other agents, sharing one engine copy at
`~/.config/strategy-terminal`:

```bash
./install.sh --claude     # ~/.claude/skills/strategy-terminal + engine
./install.sh --codex      # ~/.codex skill + /st prompt + AGENTS.md block + engine
./install.sh --all-hosts  # OpenCode (default mode) + Claude Code + Codex
./install.sh --claude --dry-run   # preview, write nothing
```

| Host | What is installed | How the agent reaches it |
|---|---|---|
| **Claude Code** | `~/.claude/skills/strategy-terminal/SKILL.md`<br>`~/.claude/skills/strategy-terminal/scripts/st` | Skills loader picks it up at startup → `/st …` or naming `strategy-terminal` |
| **Codex CLI** | `~/.codex/skills/strategy-terminal/{SKILL.md,scripts/st}`<br>`~/.codex/prompts/st.md`<br>`~/.codex/AGENTS.md` (one marked block) | `/st …` (custom prompt), and the `AGENTS.md` block tells it when to shell out |
| **Anything else** | copy `skills/strategy-terminal/` into that host's skills folder | set `ST_CLI_APP_DIR` if the engine is not at a known path |

Two host details the installer handles for you:

- Claude Code wants a lowercase skill `name`, so the frontmatter is regenerated as
  `name: strategy-terminal` and the OpenCode-only `metadata.opencode/autoinvoke` key is dropped.
  The skill body is the same file; the runner path inside it is rewritten to the host's folder.
- Codex has no skills directory, so it gets the equivalent pair: a `/st` prompt plus a block in
  `~/.codex/AGENTS.md` (delimited by `<!-- strategy-terminal:begin -->` / `:end` so uninstall can
  remove exactly that).

### Example commands

Inside Claude Code or Codex:

```
/st AAPL                          quote, stats, 1Y chart
/st "AAPL GP 6mo"                 price chart, 6 months
/st WEI                           world equity indices
/st NEWS TOP                      market headlines
/st "RISK NVDA"                   beta / alpha / VaR
/st "VOL TSLA 6mo --show"         report PDF, pages returned as images
```

From any shell, agent or not (use `~/.codex/skills/...` on Codex):

```bash
ST=~/.claude/skills/strategy-terminal/scripts/st

"$ST" --list-commands                    # every command (~140)
"$ST" AAPL                               # quote
"$ST" "AAPL GP 6mo" --no-open-images     # chart, no browser tabs
"$ST" WEI --max-rows 20
```

Add `--no-open-images` when a browser should not open: by default each exported PNG (and a
`--show` PDF) pops a tab, up to 10 per command. Charts are still written to
`<app>/cli_out/<timestamp>/<command>/`, so the agent can display them inline by reading the file.

### Uninstall

```bash
./install.sh --claude --uninstall
./install.sh --codex --uninstall
./install.sh --all-hosts --uninstall
```

Or by hand:

```bash
rm -rf ~/.claude/skills/strategy-terminal

rm -rf ~/.codex/skills/strategy-terminal
rm -f  ~/.codex/prompts/st.md
# then delete the <!-- strategy-terminal:begin --> … <!-- strategy-terminal:end --> block
# from ~/.codex/AGENTS.md
```

The engine at `~/.config/strategy-terminal` is shared by Claude Code and Codex — remove it only
when neither needs it. OpenCode's own copy at `~/.config/opencode/strategy-terminal` is untouched
by these two hosts.

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

### Why a bare `help` can still look like an invocation

Two leftovers, both now fenced off:

- **A loaded skill stays in context for the rest of the session.** `autoinvoke: false` only
  stops *new* auto-loads; after one `/st` the protocol body is still there. `SKILL.md` now says
  the protocol applies to the invocation that loaded it, and that bare words are conversation
  first. `/new` clears a loaded skill.
- **The `st.run` tool description used to list `"HELP"` as an example**, which made the bare word
  a plausible match. It now says: invoke only on an explicit data request or `/st`, and lists
  `--list-commands` instead of `HELP` as the reference command.

Neither of those is OpenCode translating text into a slash command — plain text never becomes
`/st`. It is the model choosing to call a tool because of those two texts.

If both plugin and skill are installed, the skill prefers the `st.run` tool and
falls back to `scripts/st`; either way the output is the same engine.

## Configure

Nothing is required after `./install.sh`; the bundled app is used
automatically. If you keep a venv, point at it, or override the app folder:

| Variable | Meaning | Default |
|---|---|---|
| `ST_CLI_APP_DIR` | folder containing `app-cli.py` | bundled `~/.config/opencode/strategy-terminal`, else the host-neutral `~/.config/strategy-terminal`, else the checkout's `app-cli/`, else `~/Apps/StrategyTerminal` |
| `ST_CLI_PYTHON` | interpreter with the app's dependencies | `<app>/venv/bin/python`, `<app>/.venv/bin/python`, `~/venv/bin/python`, `python3` |
| `ST_CLI_SCRIPT` | CLI file name | `app-cli.py` |
| `ST_CLI_TIMEOUT_MS` | per-command timeout | `240000` |
| `OPENCODE_CONFIG_DIR` | OpenCode config location | `~/.config/opencode` |
| `CLAUDE_CONFIG_DIR` | Claude Code config location | `~/.claude` |
| `CODEX_CONFIG_DIR` | Codex config location | `~/.codex` |
| `ST_SHARED_APP_DIR` | engine copy shared by Claude Code / Codex | `~/.config/strategy-terminal` |

API keys are **optional**. `app-cli.py` never reads them from environment
variables; it reads a local JSON file instead. The default path is
`<config-root>/strategy-terminal/keys.json` (usually `~/.config` plus
`strategy-terminal/keys.json`), or pass an explicit file with `--keys-file`:

```json
{
  "fred": "...",
  "fmp": "...",
  "alpha_vantage": "...",
  "polygon": "...",
  "newsapi_key": "...",
  "finnhub": "...",
  "alpaca_key": "...",
  "alpaca_secret": "..."
}
```

Every entry is optional. Sources that need no key at all: yfinance, CoinGecko,
GDELT, RSS feeds, World Bank, plus FRED/Yahoo fallbacks.

## Tools

| Tool | Arguments |
|---|---|
| `st.run` | `command` (required), `user`, `images`, `open_images`, `show`, `open_pdf`, `max_rows` |
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
| `--open-images` | open each exported chart PNG in the default browser (default) |
| `--no-open-images` | keep the browser closed for chart PNGs (`ST_CLI_OPEN_IMAGES=0` does the same) |
| `--user-id N` / `--email X` | act as a local account instead of anonymous |
| `--no-images` | text-only output (no PNG export, so nothing to open) |
| `--max-rows N` | limit table rows |

Any other `app-cli.py` flag can be passed through in the same way.

## Privacy and secrets

- This bundle contains **no credentials** — no API keys, tokens or passwords.
- `app-cli.py` reads keys only from a local JSON file (`keys.json` or
  `--keys-file`) and (for local accounts) from the app's own SQLite store
  `users.db`, which is **not** part of this bundle. It does not read API keys
  from the process environment.
- Credentials are never cached: `--email/--password` is verified against
  `users.db` for that run, and `--anonymous` never writes account data.
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
| `/st` missing in Claude Code | check `~/.claude/skills/strategy-terminal/SKILL.md` exists; Claude Code scans skills at startup, so restart the session |
| `/st` missing in Codex | check `~/.codex/prompts/st.md` and the `strategy-terminal:begin` block in `~/.codex/AGENTS.md`; restart `codex` |
| Claude/Codex skill runs but the engine is not found | `./install.sh --claude` (or `--codex`) places it at `~/.config/strategy-terminal`; or export `ST_CLI_APP_DIR` |
| skill runs but `app-cli.py not found` | set `ST_CLI_APP_DIR`, or re-run `./install.sh --skill-only` to place the bundled engine |
| `--show` did not open a browser | check `DISPLAY`/`WAYLAND_DISPLAY`/`BROWSER`; the PDF is still written next to the PNGs |
| browser opens too much | pass `--no-open-images` (or `open_images: false` on `st.run`), or export `ST_CLI_OPEN_IMAGES=0` |
| a command hangs | it is fetching many tickers; raise `ST_CLI_TIMEOUT_MS` |

## Uninstall

```bash
./install.sh --uninstall              # OpenCode: everything the default mode installed
./install.sh --plugin-only --uninstall
./install.sh --claude --uninstall     # Claude Code
./install.sh --codex --uninstall      # Codex CLI (+ its AGENTS.md block)
./install.sh --all-hosts --uninstall  # all three
```

By hand, for OpenCode:

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

Claude Code and Codex: `rm -rf ~/.claude/skills/strategy-terminal`, and
`rm -rf ~/.codex/skills/strategy-terminal ~/.codex/prompts/st.md` plus the
`<!-- strategy-terminal:begin --> … <!-- strategy-terminal:end -->` block in
`~/.codex/AGENTS.md` — or use `./install.sh --claude --uninstall` /
`--codex --uninstall` as shown in
[Claude Code and Codex CLI](#claude-code-and-codex-cli).

The engine is shared (`~/.config/opencode/strategy-terminal` for OpenCode,
`~/.config/strategy-terminal` for Claude Code and Codex), so remove each only when no host needs it.

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
