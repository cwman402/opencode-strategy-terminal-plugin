#!/usr/bin/env bash
# Install the Strategy Terminal integration for OpenCode, Claude Code or Codex.
#
#   ./install.sh                 OpenCode — plugin + skill + engine + /st command + bin wrapper
#   ./install.sh --plugin-only   OpenCode — the two st.* tools + the engine
#   ./install.sh --skill-only    OpenCode — skill + engine + /st (no plugin)
#   ./install.sh --claude        Claude Code — skill + engine
#   ./install.sh --codex         Codex CLI — skill + /st prompt + AGENTS.md block + engine
#   ./install.sh --all-hosts     OpenCode (default mode) + Claude Code + Codex
#   ./install.sh --uninstall     remove whatever the same flags would have installed
#   ./install.sh --dry-run       print the actions without performing them
#
# OpenCode keeps its engine at ~/.config/opencode/strategy-terminal. Claude Code
# and Codex share one host-neutral copy at ~/.config/strategy-terminal, so the
# two of them never install the engine twice.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="${OPENCODE_CONFIG_DIR:-$HOME/.config/opencode}"
CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
CODEX_DIR="${CODEX_CONFIG_DIR:-$HOME/.codex}"
SHARED_APP_DIR="${ST_SHARED_APP_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/strategy-terminal}"

DRY_RUN=false
UNINSTALL=false
MODE=all
HOSTS=()

add_host() {
  local h
  for h in "$@"; do
    case " ${HOSTS[*]:-} " in
      *" $h "*) ;;
      *) HOSTS+=("$h") ;;
    esac
  done
}

usage() {
  cat <<'EOF'
用法: ./install.sh [host flags] [mode flags] [--uninstall] [--dry-run]

Host flags (default: --opencode):
  --opencode        OpenCode — plugin + skill + engine + /st + bin wrapper
  --claude          Claude Code — skill + engine (~/.claude/skills/strategy-terminal)
  --codex           Codex CLI — skill + /st prompt + AGENTS.md block + engine
  --all-hosts       OpenCode (default mode) + Claude Code + Codex

Mode flags (OpenCode only):
  --plugin-only     only plugins/strategy-terminal.ts + the engine
                    (st.run / st.commands tools; no skill, no /st)
  --skill-only      only skills/strategy-terminal + the engine + the /st command
                    (no plugin; /st loads the skill and runs scripts/st)

Other:
  --uninstall       remove what the same flags would have installed
  --dry-run         print the actions without performing them
  -h, --help        this text

Environment overrides: OPENCODE_CONFIG_DIR, CLAUDE_CONFIG_DIR, CODEX_CONFIG_DIR,
ST_SHARED_APP_DIR.
EOF
}

for arg in "$@"; do
  case "$arg" in
    --plugin-only)
      [ "$MODE" = skill ] && { echo "install.sh: --plugin-only and --skill-only are mutually exclusive" >&2; exit 2; }
      MODE=plugin ;;
    --skill-only)
      [ "$MODE" = plugin ] && { echo "install.sh: --plugin-only and --skill-only are mutually exclusive" >&2; exit 2; }
      MODE=skill ;;
    --opencode) add_host opencode ;;
    --claude|--claude-code) add_host claude ;;
    --codex) add_host codex ;;
    --all-hosts) add_host opencode claude codex ;;
    --uninstall) UNINSTALL=true ;;
    --dry-run) DRY_RUN=true ;;
    -h|--help) usage; exit 0 ;;
    *) echo "install.sh: unknown option: $arg (try --help)" >&2; exit 2 ;;
  esac
done

[ "${#HOSTS[@]}" -eq 0 ] && HOSTS=(opencode)

if [ "$MODE" != all ]; then
  for h in "${HOSTS[@]}"; do
    if [ "$h" != opencode ]; then
      echo "install.sh: --plugin-only / --skill-only are OpenCode-only; $h has one install shape" >&2
      exit 2
    fi
  done
fi

NEED_PLUGIN=false NEED_SKILL=false NEED_EXTRAS=false
case "$MODE" in
  all)    NEED_PLUGIN=true NEED_SKILL=true NEED_EXTRAS=true ;;
  plugin) NEED_PLUGIN=true ;;
  skill)  NEED_SKILL=true NEED_EXTRAS=true ;;
esac

ENGINES_DONE=""

run() {
  if [ "$DRY_RUN" = true ]; then
    echo "would: $*"
  else
    "$@"
  fi
}

say() { printf '%s\n' "$*"; }
installed() { if [ "$DRY_RUN" = true ]; then say "  · would install $*"; else say "  ✓ $*"; fi; }
removed() { if [ "$DRY_RUN" = true ]; then say "  · would remove $*"; else say "  ✗ removed $*"; fi; }
remove_path() {
  if [ -e "$1" ] || [ -L "$1" ]; then
    run rm -rf "$1"
    removed "$1"
  fi
}

# ---- OpenCode paths ---------------------------------------------------------
OC_APP="$CONFIG_DIR/strategy-terminal"
OC_SKILL="$CONFIG_DIR/skills/strategy-terminal"
# ---- Claude Code / Codex paths ----------------------------------------------
CLAUDE_SKILL="$CLAUDE_DIR/skills/strategy-terminal"
CODEX_SKILL="$CODEX_DIR/skills/strategy-terminal"
CODEX_PROMPT="$CODEX_DIR/prompts/st.md"
CODEX_AGENTS="$CODEX_DIR/AGENTS.md"

say "Strategy Terminal installer"
say "  mode          : $([ "$UNINSTALL" = true ] && echo uninstall || echo install)"
say "  hosts         : ${HOSTS[*]}"
[ "$UNINSTALL" = false ] && case " ${HOSTS[*]} " in
  *" opencode "*)
    case "$MODE" in
      all)    say "  opencode mode : plugin + skill" ;;
      plugin) say "  opencode mode : plugin only" ;;
      skill)  say "  opencode mode : skill only" ;;
    esac
    ;;
esac
for h in "${HOSTS[@]}"; do
  case "$h" in
    opencode) say "  opencode      : $CONFIG_DIR (app $OC_APP)" ;;
    claude)   say "  claude code   : $CLAUDE_DIR (app $SHARED_APP_DIR)" ;;
    codex)    say "  codex         : $CODEX_DIR (app $SHARED_APP_DIR)" ;;
  esac
done
[ "$DRY_RUN" = true ] && say "  dry run       : nothing will be written"
say

# ---- helpers ----------------------------------------------------------------
install_engine() {
  local app="$1"
  case " $ENGINES_DONE " in
    *" $app "*) return 0 ;;
  esac
  run mkdir -p "$app"
  run cp -f "$HERE"/app-cli/*.py "$app/"
  installed "engine    $app"
  ENGINES_DONE="$ENGINES_DONE $app"
}

# Host-neutral skill: same body as the OpenCode skill, rewritten so the runner
# path matches the host's own skills folder and the frontmatter stays valid for
# Claude Code (lowercase name, no OpenCode metadata).
emit_host_skill() {
  local dest="$1" body
  body="$(mktemp)"
  awk 'BEGIN{d=0} /^---[[:space:]]*$/{ if (d<2) { d++; next } } d>=2' \
    "$HERE/skills/strategy-terminal/SKILL.md" > "$body"
  run mkdir -p "$dest/scripts"
  if [ "$DRY_RUN" = true ]; then
    say "  · would write $dest/SKILL.md"
  else
    {
      printf -- '---\n'
      printf 'name: strategy-terminal\n'
      printf 'description: Run Strategy Terminal market, macro, news, research and risk commands with the bundled app-cli.py engine. Use when the user types /st, names Strategy Terminal, or asks for a terminal command such as WEI, ECON, NEWS, AAPL GP 6mo, RISK NVDA, TRA AAPL SPY 5y.\n'
      printf -- '---\n'
      sed -e "s|\$CONFIG_ROOT/opencode/skills/strategy-terminal|$dest|" \
          -e "s|\$HOME/.config/opencode/skills/strategy-terminal|$dest|" "$body"
    } > "$dest/SKILL.md"
    say "  ✓ skill     $dest/SKILL.md"
  fi
  rm -f "$body"
  run cp -f "$HERE/skills/strategy-terminal/scripts/st" "$dest/scripts/st"
  run chmod +x "$dest/scripts/st"
  installed "runner    $dest/scripts/st"
}

write_codex_prompt() {
  run mkdir -p "$CODEX_DIR/prompts"
  if [ "$DRY_RUN" = true ]; then
    say "  · would write $CODEX_PROMPT"
    return
  fi
  cat > "$CODEX_PROMPT" <<EOF
---
description: Strategy Terminal — market, macro, news, research and risk commands
---

Read and follow the Strategy Terminal skill: \`$CODEX_SKILL/SKILL.md\`

Command for this invocation: \`\$ARGUMENTS\`

- Run the engine for real before quoting anything:
  \`"$CODEX_SKILL/scripts/st" "\$ARGUMENTS"\`
- Never answer a /st from memory or estimate a number.
- Add \`--no-open-images\` so no browser tabs open, unless the user asks for a
  report (\`--show\`).
- Show every \`![...](/abs/path/chart.png)\` line with a file read so it renders inline.
- Empty \`\$ARGUMENTS\` → run \`HELP\`.
EOF
  say "  ✓ prompt    $CODEX_PROMPT  (/st)"
}

write_codex_agents() {
  run mkdir -p "$CODEX_DIR"
  if [ -f "$CODEX_AGENTS" ] && grep -q 'strategy-terminal:begin' "$CODEX_AGENTS"; then
    say "  · AGENTS.md already has the Strategy Terminal block"
    return
  fi
  if [ "$DRY_RUN" = true ]; then
    say "  · would append the Strategy Terminal block to $CODEX_AGENTS"
    return
  fi
  if [ -s "$CODEX_AGENTS" ]; then printf '\n' >> "$CODEX_AGENTS"; fi
  cat >> "$CODEX_AGENTS" <<EOF
<!-- strategy-terminal:begin -->
## Strategy Terminal (market data)

Quotes, charts, macro, news and risk data come from the local Strategy Terminal
engine — never from memory.

- Skill: \`$CODEX_SKILL/SKILL.md\`
- Runner: \`$CODEX_SKILL/scripts/st\`
- \`/st <command>\` runs \`$CODEX_PROMPT\`

\`\`\`bash
ST="$CODEX_SKILL/scripts/st"
"\$ST" --list-commands          # every command
"\$ST" AAPL                     # quote
"\$ST" "AAPL GP 6mo" --no-open-images   # chart
\`\`\`
<!-- strategy-terminal:end -->
EOF
  say "  ✓ agents    $CODEX_AGENTS (block appended)"
}

# ---- OpenCode ---------------------------------------------------------------
do_opencode() {
  install_engine "$OC_APP"
  if [ "$NEED_PLUGIN" = true ]; then
    run mkdir -p "$CONFIG_DIR/plugins"
    run cp -f "$HERE/plugins/strategy-terminal.ts" "$CONFIG_DIR/plugins/strategy-terminal.ts"
    installed "plugin    $CONFIG_DIR/plugins/strategy-terminal.ts"
  fi
  if [ "$NEED_SKILL" = true ]; then
    run mkdir -p "$OC_SKILL/scripts"
    run cp -f "$HERE/skills/strategy-terminal/SKILL.md" "$OC_SKILL/SKILL.md"
    run cp -f "$HERE/skills/strategy-terminal/scripts/st" "$OC_SKILL/scripts/st"
    run chmod +x "$OC_SKILL/scripts/st"
    installed "skill     $OC_SKILL/  (SKILL.md + scripts/st)"
  fi
  if [ "$NEED_EXTRAS" = true ]; then
    run mkdir -p "$CONFIG_DIR/commands" "$CONFIG_DIR/bin"
    run cp -f "$HERE/commands/st.md" "$CONFIG_DIR/commands/st.md"
    run cp -f "$HERE/bin/st.sh" "$CONFIG_DIR/bin/st.sh"
    run chmod +x "$CONFIG_DIR/bin/st.sh"
    installed "command   /st  → $CONFIG_DIR/commands/st.md"
    installed "wrapper   $CONFIG_DIR/bin/st.sh  → skill runner"
  fi
}

# ---- Claude Code ------------------------------------------------------------
do_claude() {
  install_engine "$SHARED_APP_DIR"
  emit_host_skill "$CLAUDE_SKILL"
}

# ---- Codex CLI --------------------------------------------------------------
do_codex() {
  install_engine "$SHARED_APP_DIR"
  emit_host_skill "$CODEX_SKILL"
  write_codex_prompt
  write_codex_agents
}

# ---- uninstall --------------------------------------------------------------
undo_opencode() {
  if [ "$NEED_PLUGIN" = true ]; then
    remove_path "$CONFIG_DIR/plugins/strategy-terminal.ts"
  fi
  if [ "$NEED_EXTRAS" = true ]; then
    remove_path "$CONFIG_DIR/commands/st.md"
    remove_path "$CONFIG_DIR/bin/st.sh"
  fi
  if [ "$NEED_SKILL" = true ]; then
    remove_path "$OC_SKILL"
  fi
  remove_path "$OC_APP"
}

undo_claude() {
  remove_path "$CLAUDE_SKILL"
}

undo_codex() {
  remove_path "$CODEX_SKILL"
  remove_path "$CODEX_PROMPT"
  if [ -f "$CODEX_AGENTS" ] && grep -q 'strategy-terminal:begin' "$CODEX_AGENTS"; then
    if [ "$DRY_RUN" = true ]; then
      say "  · would delete the Strategy Terminal block from $CODEX_AGENTS"
    else
      sed -i '/<!-- strategy-terminal:begin -->/,/<!-- strategy-terminal:end -->/d' "$CODEX_AGENTS"
      say "  ✗ block     removed from $CODEX_AGENTS"
    fi
  fi
}

for h in "${HOSTS[@]}"; do
  if [ "$UNINSTALL" = true ]; then
    "undo_$h"
  else
    "do_$h"
  fi
done

if [ "$UNINSTALL" = true ]; then
  say ""
  say "The shared engine stays at:"
  say "  $OC_APP   (OpenCode)"
  say "  $SHARED_APP_DIR   (Claude Code / Codex)"
  say "Delete either one directly if no host needs it."
  say ""
  exit 0
fi

say ""

# ---- dependency report ------------------------------------------------------
PYTHON="${ST_CLI_PYTHON:-}"
if [ -z "$PYTHON" ]; then
  for candidate in "$OC_APP/venv/bin/python" "$OC_APP/.venv/bin/python" \
                   "$SHARED_APP_DIR/venv/bin/python" "$SHARED_APP_DIR/.venv/bin/python" \
                   "$HOME/venv/bin/python"; do
    [ -x "$candidate" ] && { PYTHON="$candidate"; break; }
  done
fi
[ -z "$PYTHON" ] && PYTHON="python3"

if command -v "$PYTHON" >/dev/null 2>&1; then
  if "$PYTHON" - <<'PY' >/dev/null 2>&1
import importlib
for mod in ("numpy", "pandas", "plotly", "requests", "scipy", "sklearn", "reportlab", "fitz", "yfinance"):
    importlib.import_module(mod)
PY
  then
    say "  ✓ python    $PYTHON — engine dependencies present"
  else
    say "  ! python    $PYTHON — missing some engine dependencies"
    say "              pip install numpy pandas plotly requests scipy scikit-learn reportlab pymupdf kaleido yfinance"
  fi
  if "$PYTHON" -c "import kaleido" >/dev/null 2>&1; then
    say "  ✓ charts    kaleido present"
  else
    say "  ! charts    kaleido missing — PNG charts will be skipped (plotly_get_chrome -y)"
  fi
else
  say "  ! python    $PYTHON not found — set ST_CLI_PYTHON to an interpreter with the engine deps"
fi

cat <<EOF

Next steps:

  1. API keys are optional and are never read from environment variables.
     Put any keys you have in a local JSON file (the engine reads it
     automatically):
       ${XDG_CONFIG_HOME:-$HOME/.config}/strategy-terminal/keys.json
     Example: {"fred": "...", "fmp": "...", "polygon": "..."}
     Or pass an explicit file with:  --keys-file /path/to/keys.json

EOF

for h in "${HOSTS[@]}"; do
  case "$h" in
    opencode)
      case "$MODE" in
        all)
          cat <<EOF
  [OpenCode]
  2. Restart OpenCode (or wait for the config watcher), then try:
       /st AAPL
       /st VOL TSLA 6mo --show
     or just ask: " AAPL 現在多少？出張 6 個月圖 "
EOF
          ;;
        plugin)
          cat <<EOF
  [OpenCode]
  2. Restart OpenCode, then ask in a new session:
       "AAPL 現在多少？出張 6 個月圖"
     (tools only — no skill, no /st command)
     Add the rest later with:  ./install.sh
EOF
          ;;
        skill)
          cat <<EOF
  [OpenCode]
  2. Skills hot-reload — usually no restart needed. Try:
       /st AAPL
       /st VOL TSLA 6mo
     The skill is explicit-only (autoinvoke: false); /st or naming
     "strategy-terminal" is what loads it. No plugin tools in this mode.
     Or run it yourself:
       $OC_SKILL/scripts/st --list-commands | head
EOF
          ;;
      esac
      ;;
    claude)
      cat <<EOF
  [Claude Code]
  2. Start a session and type:
       /st AAPL
       /st "VOL TSLA 6mo" --show
     Claude Code reads skills from ~/.claude/skills at startup, so restart the
     session if it was already running. Run it yourself with:
       $CLAUDE_SKILL/scripts/st --list-commands | head
EOF
      ;;
    codex)
      cat <<EOF
  [Codex CLI]
  2. Start codex and type:
       /st AAPL
       /st "AAPL GP 6mo"
     Codex reads ~/.codex/prompts and ~/.codex/AGENTS.md at startup.
     Run it yourself with:
       $CODEX_SKILL/scripts/st --list-commands | head
EOF
      ;;
  esac
done

say ""
