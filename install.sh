#!/usr/bin/env bash
# Install the Strategy Terminal integration for OpenCode.
#
#   ./install.sh                 plugin + skill + engine + /st command + bin wrapper
#   ./install.sh --plugin-only   the two st.* tools + the engine
#   ./install.sh --skill-only    the skill + engine + /st (no plugin)
#   ./install.sh --dry-run       show what would happen (combine with any mode)
#
# Everything lands under ~/.config/opencode (override with OPENCODE_CONFIG_DIR).
# The bundled app-cli/ is a self-contained copy of the StrategyTerminal command
# engine, so no separate StrategyTerminal checkout is required.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="${OPENCODE_CONFIG_DIR:-$HOME/.config/opencode}"
APP_DIR="$CONFIG_DIR/strategy-terminal"
SKILL_DIR="$CONFIG_DIR/skills/strategy-terminal"
DRY_RUN=false
MODE=all

usage() {
  cat <<'EOF'
用法: ./install.sh [--plugin-only | --skill-only] [--dry-run]

  (no flag)       plugin + skill + engine + /st command + bin wrapper  ← default
  --plugin-only   only plugins/strategy-terminal.ts + the engine
                  (st.run / st.commands tools; no skill, no /st)
  --skill-only    only skills/strategy-terminal + the engine + the /st command
                  (no plugin; /st loads the skill and runs scripts/st)
  --dry-run       print the actions without performing them

  OPENCODE_CONFIG_DIR=/path   install into a different config directory
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
    --dry-run) DRY_RUN=true ;;
    -h|--help) usage; exit 0 ;;
    *) echo "install.sh: unknown option: $arg (try --help)" >&2; exit 2 ;;
  esac
done

NEED_PLUGIN=false NEED_SKILL=false NEED_EXTRAS=false
case "$MODE" in
  all)    NEED_PLUGIN=true NEED_SKILL=true NEED_EXTRAS=true ;;
  plugin) NEED_PLUGIN=true ;;
  skill)  NEED_SKILL=true NEED_EXTRAS=true ;;
esac

run() {
  if [ "$DRY_RUN" = true ]; then
    echo "would: $*"
  else
    "$@"
  fi
}

say() { printf '%s\n' "$*"; }
installed() { if [ "$DRY_RUN" = true ]; then say "  · would install $*"; else say "  ✓ $*"; fi; }

say "Strategy Terminal installer"
case "$MODE" in
  all)    say "  mode          : plugin + skill" ;;
  plugin) say "  mode          : plugin only" ;;
  skill)  say "  mode          : skill only" ;;
esac
say "  plugin config : $CONFIG_DIR"
say "  bundled app   : $APP_DIR"
[ "$DRY_RUN" = true ] && say "  dry run       : nothing will be written"
say

# ---- engine (both modes need it) -------------------------------------------
run mkdir -p "$APP_DIR"
run cp -f "$HERE"/app-cli/*.py "$APP_DIR/"
installed "engine    $APP_DIR"

# ---- plugin -----------------------------------------------------------------
if [ "$NEED_PLUGIN" = true ]; then
  run mkdir -p "$CONFIG_DIR/plugins"
  run cp -f "$HERE/plugins/strategy-terminal.ts" "$CONFIG_DIR/plugins/strategy-terminal.ts"
  installed "plugin    $CONFIG_DIR/plugins/strategy-terminal.ts"
fi

# ---- skill ------------------------------------------------------------------
if [ "$NEED_SKILL" = true ]; then
  run mkdir -p "$SKILL_DIR/scripts"
  run cp -f "$HERE/skills/strategy-terminal/SKILL.md" "$SKILL_DIR/SKILL.md"
  run cp -f "$HERE/skills/strategy-terminal/scripts/st" "$SKILL_DIR/scripts/st"
  run chmod +x "$SKILL_DIR/scripts/st"
  installed "skill     $SKILL_DIR/  (SKILL.md + scripts/st)"
fi

# ---- slash command + CLI wrapper -------------------------------------------
if [ "$NEED_EXTRAS" = true ]; then
  run mkdir -p "$CONFIG_DIR/commands" "$CONFIG_DIR/bin"
  run cp -f "$HERE/commands/st.md" "$CONFIG_DIR/commands/st.md"
  run cp -f "$HERE/bin/st.sh" "$CONFIG_DIR/bin/st.sh"
  run chmod +x "$CONFIG_DIR/bin/st.sh"
  installed "command   /st  → $CONFIG_DIR/commands/st.md"
  installed "wrapper   $CONFIG_DIR/bin/st.sh  → skill runner"
fi

say

# ---- dependency report ------------------------------------------------------
PYTHON="${ST_CLI_PYTHON:-}"
if [ -z "$PYTHON" ]; then
  for candidate in "$APP_DIR/venv/bin/python" "$APP_DIR/.venv/bin/python" "$HOME/venv/bin/python"; do
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

  1. API keys are optional and never stored by this integration. Export in your
     shell to enable the extra sources:
       FRED_API_KEY  FMP_API_KEY  ALPHA_VANTAGE_API_KEY  POLYGON_API_KEY
       NEWSAPI_KEY   FINNHUB_API_KEY  OPENROUTER_API_KEY

EOF

case "$MODE" in
  all)
    cat <<EOF
  2. Restart OpenCode (or wait for the config watcher), then try:
       /st AAPL
       /st VOL TSLA 6mo --show
     or just ask: " AAPL 現在多少？出張 6 個月圖 "
EOF
    ;;
  plugin)
    cat <<EOF
  2. Restart OpenCode, then ask in a new session:
       "AAPL 現在多少？出張 6 個月圖"
     (tools only — no skill, no /st command)
     Add the rest later with:  ./install.sh
EOF
    ;;
  skill)
    cat <<EOF
  2. Skills hot-reload — usually no restart needed. Try:
       /st AAPL
       /st VOL TSLA 6mo
     The skill is explicit-only (autoinvoke: false); /st or naming
     "strategy-terminal" is what loads it. No plugin tools in this mode.
     Or run it yourself:
       $SKILL_DIR/scripts/st --list-commands | head
EOF
    ;;
esac

say ""
