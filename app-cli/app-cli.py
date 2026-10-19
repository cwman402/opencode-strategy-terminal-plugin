#!/usr/bin/env python3
"""
app-cli.py – Command-line front-end for the StrategyTerminal Streamlit app.

Runs the *same* command engine as the Streamlit "Strategy Terminal" page
(terminal.py / features.py) without a browser.  A headless Streamlit shim
captures every `st.*` call, and a renderer turns those captures into:

  • markdown text        → printed to stdout (renders in the OpenCode chat)
  • dataframes           → markdown tables
  • plotly figures       → PNG images (kaleido + chrome), linked as markdown
  • download buttons     → files written next to the images

Usage
-----
    python app-cli.py "AAPL"                 # one-shot command
    python app-cli.py "AAPL GP 1y" "WEI"     # several commands
    python app-cli.py -c "VOL TSLA 6mo"      # explicit -c
    python app-cli.py --anonymous "WEI"      # no login (market data only)
    python app-cli.py --user-id 1 "WL"       # act as a stored user
    python app-cli.py --email me@x.com --password "<your-password>" "PNL"
    python app-cli.py -i                     # interactive REPL
    python app-cli.py --list-commands        # command reference
    echo "AAPL" | python app-cli.py          # commands from stdin

Notes
-----
* The working directory is forced to this file's folder so `users.db`,
  `uploads/`, `logs/` resolve exactly like they do under Streamlit.
* Credentials: `--email/--password` (or `$ST_CLI_PASSWORD`) are verified against
  users.db; the first successful login is remembered in
  `~/.config/strategy-terminal/cli.json` and reused.  `--user-id` skips the
  password because the database is local; use `--anonymous` to skip login.
* API keys come from the user's saved keys, then `--keys-file`, then
  environment variables (`FRED_API_KEY`, `FMP_API_KEY`, `POLYGON_API_KEY`,
  `NEWSAPI_KEY`, `ALPHA_VANTAGE_API_KEY`, `FINNHUB_API_KEY`, …).
* Buttons that gate output (e.g. "▶ Run Screen") are auto-pressed; the run is
  noted in the output.  `--no-autopress` disables that, `--press LABEL` forces
  any other button.
* Charts are exported as PNG (plotly + kaleido + Chrome) and printed as
  markdown image links; `--no-images` falls back to text/sparkline summaries.
* Price alerts are stored, but the e-mail scheduler only runs inside the
  Streamlit process (it needs a long-lived server) — the CLI only manages them.
* Output artefacts (PNGs, CSV, PDF) go to `cli_out/<timestamp>/` by default.
"""
from __future__ import annotations

import argparse
import html as _htmllib
import json
import os
import pathlib
import re
import sqlite3
import sys
import time
import types
from datetime import datetime
from html.parser import HTMLParser

# ── Force the app folder as CWD (database.py uses the relative path users.db) ──
APP_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(APP_DIR)

SESSION_FILE = os.path.expanduser('~/.config/strategy-terminal/cli.json')
DEFAULT_OUT_ROOT = os.path.join(APP_DIR, 'cli_out')
DB_FILE = os.path.join(APP_DIR, 'users.db')


# ══════════════════════════════════════════════════════════════════════════════
#  1.  Headless Streamlit shim
# ══════════════════════════════════════════════════════════════════════════════

class _Rerun(Exception):
    """Raised when captured code calls st.rerun()."""


class _Stop(Exception):
    """Raised when captured code calls st.stop()."""


class _SessionState(dict):
    """dict with attribute access, like st.session_state."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)

    def __setattr__(self, name, value):
        self[name] = value

    def __delattr__(self, name):
        try:
            del self[name]
        except KeyError:
            raise AttributeError(name)


class _Any:
    """Permissive stand-in: callable, context manager, attribute sink."""

    def __call__(self, *a, **k):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        return self

    def __iter__(self):
        return iter(())

    def __bool__(self):
        return False


# Every captured element: {'kind': str, 'payload': ...}
ELEMENTS: list = []
DOWNLOAD_FILES: dict = {}
UNKNOWN_APIS: set = set()

# Buttons whose click the CLI assumes (command handlers gate output on them).
_AUTOPRESS_RE = re.compile(
    r'^\s*[▶►]?\s*(run|apply|go|generate|screen|build|load|refresh|compute|'
    r'calculate|show|update|submit|start)\b', re.IGNORECASE)
FORCED_PRESSED: set = set()

_SKIP_HTML = {'script', 'style', 'head', 'meta', 'link'}
_TEXT_AS_MD = {'b': '**', 'strong': '**', 'i': '*', 'em': '*', 'code': '`'}
_INLINE_SPACED = {'span', 'small', 'sup', 'sub', 'font', 'label'}
_BLOCK_TAGS = {
    'div', 'p', 'br', 'tr', 'td', 'th', 'table', 'li', 'ul', 'ol', 'hr',
    'section', 'article', 'header', 'footer', 'pre', 'blockquote',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
}


class _HTMLToMarkdown(HTMLParser):
    """Very small HTML → markdown/text converter used for st.markdown(html)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0
        self._link: list[str | None] = []

    # -- helpers ------------------------------------------------------------
    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_HTML:
            self._skip += 1
            return
        if self._skip:
            return
        if tag == 'br':
            self.parts.append('\n')
        elif tag == 'a':
            href = dict(attrs).get('href', '')
            self._link.append(href)
            self.parts.append(' [')
        elif tag in _TEXT_AS_MD:
            self.parts.append(_TEXT_AS_MD[tag])
        elif tag in _INLINE_SPACED:
            self.parts.append(' ')
        elif tag in _BLOCK_TAGS:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in _SKIP_HTML:
            self._skip = max(0, self._skip - 1)
            return
        if self._skip:
            return
        if tag == 'a':
            href = self._link.pop() if self._link else ''
            self.parts.append(f']({href}) ' if href else '] ')
        elif tag in _TEXT_AS_MD:
            self.parts.append(_TEXT_AS_MD[tag])
        elif tag in _INLINE_SPACED:
            self.parts.append(' ')
        elif tag in _BLOCK_TAGS:
            self.parts.append('\n')

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)

    def text(self) -> str:
        raw = ''.join(self.parts).replace('\xa0', ' ')
        lines = []
        for ln in raw.splitlines():
            ln = re.sub(r'[ \t]+', ' ', ln).strip()
            ln = re.sub(r'\s+([,.;:!?%)\]])', r'\1', ln)
            ln = re.sub(r'([(\[])\s+', r'\1', ln)
            lines.append(ln)
        out, blanks = [], 0
        for ln in lines:
            if ln:
                out.append(ln)
                blanks = 0
            elif blanks == 0:
                out.append('')
                blanks = 1
        return '\n'.join(out).strip()


def html_to_text(s: str) -> str:
    """Convert an HTML blob to readable markdown-ish text; pass plain md through."""
    if not isinstance(s, str):
        return str(s)
    if '<' not in s:
        return s.strip()
    p = _HTMLToMarkdown()
    try:
        p.feed(s)
        p.close()
    except Exception:
        return re.sub(r'<[^>]+>', ' ', s).strip()
    txt = p.text()
    return txt if txt else ''


def _squash(s: str) -> str:
    """Collapse runs of whitespace while keeping line structure (CSS text etc.)."""
    if not isinstance(s, str):
        return str(s)
    if '<' in s:
        return html_to_text(s)
    return s.strip()


def _build_streamlit_stub() -> types.ModuleType:
    """Create a fake `streamlit` module that records rendering calls."""
    st = types.ModuleType('streamlit')
    st.session_state = _SessionState()
    st.query_params = _SessionState()
    st.secrets = {}
    st.cache_data = _cache_factory
    st.cache_resource = _cache_factory
    st.experimental_memo = _cache_factory
    st.experimental_singleton = _cache_factory
    st.fragment = _cache_factory
    st.column_config = _Any()
    st.components = _Any()
    st.sidebar = _Proxy()

    def _capture(kind, payload=None):
        ELEMENTS.append({'kind': kind, 'payload': payload})

    # ── text-ish ───────────────────────────────────────────────────────────
    def markdown(body='', *a, **k):
        txt = _squash(str(body))
        if txt:
            _capture('md', txt)

    def write(body='', *a, **k):
        if hasattr(body, 'to_dict') or hasattr(body, 'to_string'):
            _capture('table', body)
        else:
            txt = _squash(str(body))
            if txt:
                _capture('md', txt)

    def code(body='', language=None, **k):
        _capture('code', str(body))

    def caption(body='', **k):
        txt = _squash(str(body))
        if txt:
            _capture('caption', txt)

    def text(body='', **k):
        txt = _squash(str(body))
        if txt:
            _capture('md', txt)

    def latex(body='', **k):
        _capture('code', str(body))

    def echo():
        pass

    def _level(kind, body, icon):
        txt = _squash(str(body))
        if txt:
            _capture(kind, f"{icon} {txt}")

    st.error = lambda body='', *a, **k: _level('alert_error', body, '❌')
    st.warning = lambda body='', *a, **k: _level('alert_warning', body, '⚠️')
    st.info = lambda body='', *a, **k: _level('alert_info', body, 'ℹ️')
    st.success = lambda body='', *a, **k: _level('alert_success', body, '✅')
    st.toast = lambda body='', **k: _level('alert_info', body, 'ℹ️')

    def exception(exc, *a, **k):
        _capture('traceback', ''.join(__import__('traceback').format_exception(
            type(exc), exc, exc.__traceback__)) if isinstance(exc, BaseException) else str(exc))

    st.exception = exception
    st.markdown, st.write, st.code, st.caption, st.text, st.latex, st.echo = \
        markdown, write, code, caption, text, latex, echo
    st.title = lambda body='', **k: (st.markdown(f"# {body}") if str(body).strip() else None)
    st.header = lambda body='', **k: (st.markdown(f"## {body}") if str(body).strip() else None)
    st.subheader = lambda body='', **k: (st.markdown(f"### {body}") if str(body).strip() else None)
    st.divider = lambda *a, **k: _capture('divider')
    st.json = lambda obj, *a, **k: _capture('json', obj)
    st.metric = lambda label, value, delta=None, **k: _capture(
        'metric', {'label': str(label), 'value': value, 'delta': delta})
    st.badge = lambda label, **k: _capture('md', f"`{label}`")

    # ── data ───────────────────────────────────────────────────────────────
    def dataframe(data=None, *a, **k):
        if data is not None:
            _capture('table', data)

    def data_editor(data=None, *a, **k):
        if data is not None:
            _capture('table', data)
        return data

    st.dataframe, st.table, st.data_editor = dataframe, dataframe, data_editor

    # ── charts ─────────────────────────────────────────────────────────────
    def plotly_chart(fig, *a, **k):
        _capture('chart', {'fig': fig, 'height': k.get('height') or _fig_height(fig),
                           'caption': k.get('caption', '')})

    st.plotly_chart = plotly_chart
    st.altair_chart = st.vega_lite_chart = st.plotly_chart = plotly_chart
    st.map = st.pydeck_chart = lambda *a, **k: None
    st.image = lambda img, *a, **k: _capture('image', img)

    def pyplot(fig=None, *a, **k):
        if fig is not None:
            _capture('chart', {'fig': fig, 'height': 400, 'caption': '', 'mpl': True})

    st.pyplot = pyplot
    for _chart in ('line_chart', 'bar_chart', 'area_chart', 'scatter_chart'):
        setattr(st, _chart, _stub_chart_factory(_chart))

    # ── layout / containers ────────────────────────────────────────────────
    def columns(spec=1, *a, **k):
        n = spec if isinstance(spec, int) else len(spec)
        return [_Proxy() for _ in range(max(1, int(n)))]

    def tabs(labels, *a, **k):
        return [_Proxy() for _ in labels] if not isinstance(labels, int) else \
            [_Proxy() for _ in range(labels)]

    st.columns, st.tabs = columns, tabs
    st.container = st.empty = st.expander = st.form = st.popover = \
        st.spinner = st.status = st.dialog = lambda *a, **k: _Proxy()
    st.sidebar = _Proxy()
    st.bottom = _Proxy()

    def progress(value=0, *a, **k):
        _capture('progress', value)
        return _Proxy()

    st.progress = progress
    st.stop = lambda *a, **k: (_ for _ in ()).throw(_Stop())
    st.rerun = lambda *a, **k: (_ for _ in ()).throw(_Rerun())
    st.switch_page = lambda *a, **k: None

    # ── inputs (never interactive: return neutral defaults) ────────────────
    # Buttons: most handlers gate on a "Run / Apply" style button.  Those are
    # auto-pressed so the command actually executes; per-item buttons (search
    # result ▶ TICKER, etc.) stay unpressed.
    def button(label='', *a, **k):
        text = str(label)
        pressed = bool(_AUTOPRESS_RE.match(text)) or text.strip() in FORCED_PRESSED
        if pressed:
            _capture('action', text)
        return pressed

    def download_button(label='', data=None, file_name=None, *a, **k):
        if data is not None:
            DOWNLOAD_FILES[str(label or file_name or 'download')] = (
                str(file_name or 'download.bin'), data)
        return False

    def text_input(*a, **k):
        if k.get('value') is not None:
            return k['value']
        return a[1] if len(a) > 1 and a[1] is not None else ''

    def text_area(*a, **k):
        if k.get('value') is not None:
            return k['value']
        return a[1] if len(a) > 1 and a[1] is not None else ''

    def number_input(*a, **k):
        # st.number_input(label, min_value, max_value, value, step, ...)
        if k.get('value') is not None:
            return k['value']
        if len(a) > 3 and a[3] is not None:
            return a[3]
        if len(a) > 1 and a[1] is not None:
            return a[1]
        return 0.0

    def selectbox(label='', options=(), index=0, **k):
        options = list(options)
        if not options:
            return None
        try:
            return options[k.get('index', index) or 0]
        except Exception:
            return options[0]

    def _first_option(label='', options=(), **k):
        options = list(options)
        return options[0] if options else None

    def slider(*a, **k):
        # st.slider(label, min_value, max_value, value, step, ...)
        if k.get('value') is not None:
            return k['value']
        if len(a) > 3 and a[3] is not None:
            return a[3]
        if len(a) > 1 and a[1] is not None:
            return a[1]
        return 0

    st.button = button
    st.form_submit_button = lambda label='', *a, **k: False
    st.download_button = download_button
    st.text_input, st.text_area, st.number_input = text_input, text_area, number_input
    st.selectbox, st.radio, st.select_slider = selectbox, _first_option, _first_option
    st.slider = slider
    st.checkbox = st.toggle = lambda *a, **k: k.get('value', a[1] if len(a) > 1 else False)
    st.multiselect = lambda *a, **k: list(k.get('default') or [])
    st.file_uploader = lambda *a, **k: None
    st.color_picker = lambda *a, **k: k.get('value', a[1] if len(a) > 1 else '#000000')
    st.date_input = lambda *a, **k: k.get('value', a[1] if len(a) > 1 else None)
    st.time_input = lambda *a, **k: k.get('value', a[1] if len(a) > 1 else None)
    st.camera_input = lambda *a, **k: None

    # ── misc ───────────────────────────────────────────────────────────────
    st.set_page_config = lambda *a, **k: None
    st.set_option = st.get_option = lambda *a, **k: None
    st.audio = st.video = lambda *a, **k: None
    st.help = st.connection = lambda *a, **k: _Any()

    def __getattr__(name):          # pragma: no cover - safety net
        UNKNOWN_APIS.add(name)
        return _Any()

    st.__getattr__ = __getattr__
    return st


def _fig_height(fig) -> int:
    try:
        return int(fig.layout.height or 420)
    except Exception:
        return 420


def _stub_chart_factory(name):
    """line_chart / bar_chart / … → convert to a plotly figure when possible."""
    def _fn(data=None, *a, **k):
        try:
            import pandas as pd
            import plotly.graph_objects as go
            if data is None:
                return None
            fig = go.Figure()
            if isinstance(data, dict):
                for label, series in data.items():
                    import pandas as _pd
                    s = _pd.Series(series)
                    if name == 'bar_chart':
                        fig.add_bar(x=[str(i) for i in s.index], y=s.values, name=str(label))
                    else:
                        fig.add_scatter(x=[str(i) for i in s.index], y=s.values,
                                        name=str(label), mode='lines')
            else:
                df = pd.DataFrame(data)
                for col in df.columns:
                    if name == 'bar_chart':
                        fig.add_bar(x=[str(i) for i in df.index], y=df[col], name=str(col))
                    else:
                        fig.add_scatter(x=[str(i) for i in df.index], y=df[col],
                                        name=str(col), mode='lines')
            _capture_chart({'fig': fig, 'height': _fig_height(fig), 'caption': ''})
        except Exception:
            pass
        return None
    return _fn


def _capture_chart(payload):
    ELEMENTS.append({'kind': 'chart', 'payload': payload})


class _Proxy:
    """Context-manager stand-in for st.columns()[i] / st.tabs()[i] / st.expander()."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __getattr__(self, name):
        return getattr(sys.modules['streamlit'], name)


def _cache_factory(*dargs, **dkw):
    """@st.cache_data / @st.cache_resource → passthrough with a light memo."""
    memo: dict = {}
    disabled = os.environ.get('ST_CLI_NO_CACHE') == '1'

    def _decorate(fn):
        def wrapper(*args, **kwargs):
            if disabled:
                return fn(*args, **kwargs)
            try:
                key = (repr(args), repr(sorted(kwargs.items())))
                hash(key)
            except Exception:
                return fn(*args, **kwargs)
            if key in memo:
                return memo[key]
            val = fn(*args, **kwargs)
            memo[key] = val
            return val

        wrapper.__name__ = getattr(fn, '__name__', 'cached')
        wrapper.clear = memo.clear                   # parity with st.cache_data
        wrapper.__wrapped__ = fn
        return wrapper

    # Bare usage: @st.cache_data
    if len(dargs) == 1 and callable(dargs[0]) and not dkw:
        return _decorate(dargs[0])
    return _decorate


# Install BEFORE anything imports streamlit
sys.modules['streamlit'] = _build_streamlit_stub()
_STUB = sys.modules['streamlit']


# ══════════════════════════════════════════════════════════════════════════════
#  2.  Renderer — captured elements → terminal / markdown / files
# ══════════════════════════════════════════════════════════════════════════════

_SPARK_CHARS = '▁▂▃▄▅▆▇█'
_NUM_RE = re.compile(r'^-?[\d,]*\.?\d+%?$')
_CARD_RE = re.compile(r'^(.{1,40}?)\n(.{1,60})$')


def coalesce_cards(elements):
    """Merge runs of `label\\nvalue` markdown cards into one key/value grid.

    cmd_overview() and friends render each statistic as its own
    `col.markdown("<span>label</span><br><span>value</span>")` card; in a
    terminal that is 30 tiny blocks.  Grouped, they become one tidy table.
    """
    out: list = []
    i = 0
    while i < len(elements):
        el = elements[i]
        if el['kind'] == 'md':
            j, cards = i, []
            while j < len(elements) and elements[j]['kind'] == 'md':
                m = _CARD_RE.match(elements[j]['payload'].strip())
                if not m:
                    break
                label = m.group(1).strip().strip(':')
                value = m.group(2).strip()
                if not label or not value:
                    break
                cards.append((label, value))
                j += 1
            if len(cards) >= 3:
                out.append({'kind': 'kvgrid', 'payload': cards})
                i = j
                continue

            # Fallback: runs of short multi-line cards (dashboards like WEI /
            # movers) become one compact line each instead of N loose blocks.
            j, items = i, []
            while j < len(elements) and elements[j]['kind'] == 'md':
                ls = [l for l in elements[j]['payload'].splitlines() if l.strip()]
                if not (2 <= len(ls) <= 6) or any(len(l) > 45 for l in ls):
                    break
                items.append(' · '.join(ls))
                j += 1
            if len(items) >= 4:
                out.append({'kind': 'block', 'payload': items})
                i = j
                continue
        out.append(el)
        i += 1
    return out


def _sparkline(values) -> str:
    nums = [v for v in values if isinstance(v, (int, float))]
    if len(nums) < 2:
        return ''
    lo, hi = min(nums), max(nums)
    if hi == lo:
        return _SPARK_CHARS[0] * len(nums)
    return ''.join(_SPARK_CHARS[min(7, int((v - lo) / (hi - lo) * 7.99))] for v in nums)


def _fmt_num(v):
    if isinstance(v, float):
        if v != v:                                  # NaN
            return ''
        if abs(v) >= 1000:
            return f"{v:,.2f}"
        if v == int(v):
            return f"{int(v):,}"
        return f"{v:,.4f}".rstrip('0').rstrip('.')
    return str(v)


def _cell(v, maxw: int = 48) -> str:
    if v is None:
        return ''
    if isinstance(v, float) and v != v:
        return ''
    s = _fmt_num(v) if isinstance(v, (int, float)) else str(v)
    s = s.replace('\n', ' ').replace('|', '\\|').strip()
    return s if len(s) <= maxw else s[:maxw - 1] + '…'


def _to_dataframe(data):
    import pandas as pd
    if isinstance(data, pd.DataFrame):
        return data
    # pandas Styler (st.dataframe(df.style...) is used in places)
    if data.__class__.__name__ == 'Styler':
        inner = getattr(data, 'data', None)
        if isinstance(inner, pd.DataFrame):
            return inner
    if isinstance(data, pd.Series):
        return data.to_frame()
    if hasattr(data, 'shape') and hasattr(data, 'dtype') and len(getattr(data, 'shape', ())) == 2:
        try:
            return pd.DataFrame(data)
        except Exception:
            pass
    if isinstance(data, dict):
        try:
            return pd.DataFrame(data)
        except Exception:
            return pd.DataFrame({'value': list(data.values())}, index=list(data.keys()))
    if isinstance(data, (list, tuple)):
        try:
            return pd.DataFrame(data)
        except Exception:
            return pd.DataFrame({'value': list(data)})
    return pd.DataFrame({'value': [str(data)]})


def render_table(data, max_rows: int = 60, out=None) -> None:
    """Print a dataframe as a markdown pipe table."""
    out = out or sys.stdout
    try:
        df = _to_dataframe(data)
    except Exception as e:
        print(f"(table unavailable: {e})", file=out)
        return
    if df.empty:
        print("_(empty table)_", file=out)
        return

    total = len(df)
    show = df.head(max_rows).copy()

    # Promote a meaningful index to a column
    idx = show.index
    if not (idx.name is None and list(idx) == list(range(len(show)))):
        name = str(idx.name) if idx.name is not None else 'index'
        show = show.reset_index().rename(columns={'index': name})

    cols = [str(c) for c in show.columns]
    if len(cols) > 12:                                # very wide → vertical layout
        for i, (_, row) in enumerate(show.iterrows(), 1):
            print(f"**{i}.** " + ' · '.join(f"{c}: {_cell(row[c], 40)}" for c in cols), file=out)
        if total > len(show):
            print(f"_(+{total - len(show)} more rows)_", file=out)
        return

    print('| ' + ' | '.join(cols) + ' |', file=out)
    print('|' + '|'.join([' --- '] * len(cols)) + '|', file=out)
    for _, row in show.iterrows():
        print('| ' + ' | '.join(_cell(row[c]) for c in cols) + ' |', file=out)
    if total > len(show):
        print(f"_(+{total - len(show)} more rows)_", file=out)


def save_chart(payload, out_dir: str, index: int, console_out, max_traces: int = 3):
    """Write a figure to PNG and emit a markdown image link."""
    fig = payload['fig']
    caption = payload.get('caption') or ''
    height = payload.get('height') or 420

    # matplotlib figure?
    if payload.get('mpl'):
        path = os.path.join(out_dir, f'chart_{index:02d}.png')
        try:
            fig.savefig(path, dpi=140, bbox_inches='tight')
        except Exception as e:
            print(f"(chart could not be saved: {e})", file=console_out)
            return
        print(f"![{caption or 'chart'}]({path})", file=console_out)
        return

    title = ''
    try:
        title = str(fig.layout.title.text or '')
    except Exception:
        pass

    path = os.path.join(out_dir, f'chart_{index:02d}.png')
    try:
        fig.write_image(path, width=1150, height=int(height), scale=2)
    except Exception as e:
        # Fall back to a text description of the traces
        print(f"_chart not rendered as image ({type(e).__name__}); text summary:_",
              file=console_out)
        _render_chart_text(fig, console_out, max_traces)
        return

    alt = caption or title or f'chart {index}'
    # Keep the markdown alt text simple: em dashes / odd punctuation can stop
    # chat renderers from resolving the image link.
    alt = re.sub(r'[^A-Za-z0-9 ._%+()\-/]', ' ', alt)
    alt = re.sub(r'\s+', ' ', alt).strip() or f'chart {index}'
    print(f"![{alt}]({path})", file=console_out)
    print(f"_{title}_  \n`{path}`" if title else f"`{path}`", file=console_out)


def _render_chart_text(fig, out, max_traces: int = 3):
    traces = getattr(fig, 'data', []) or []
    for t in list(traces)[:max_traces]:
        name = getattr(t, 'name', '') or getattr(t, 'type', 'trace')
        try:
            y = getattr(t, 'y', None)
            y = [] if y is None else list(y)
        except Exception:
            y = []
        spark = _sparkline(y)
        head = f"**{name}**"
        if spark:
            head += f"  `{spark}`"
        print(head, file=out)
        if y:
            tail = ', '.join(_cell(v, 16) for v in y[-6:])
            print(f"  last: {tail}", file=out)
    if len(traces) > max_traces:
        print(f"_(+{len(traces) - max_traces} more series)_", file=out)


def render_elements(elements, out_dir: str, out=None, images: bool = True,
                    max_rows: int = 60, show_tracebacks: bool = False,
                    save_data: bool = False) -> None:
    """Render everything the command produced."""
    out = out or sys.stdout
    elements = coalesce_cards(elements)
    chart_no = 0
    table_no = 0

    for el in elements:
        kind, payload = el['kind'], el.get('payload')

        if kind in ('md', 'caption'):
            if payload.strip():
                print(payload, file=out)
                print(file=out)

        elif kind == 'code':
            print('```', file=out)
            print(payload, file=out)
            print('```', file=out)

        elif kind == 'divider':
            print('\n---\n', file=out)

        elif kind == 'json':
            try:
                print('```json', file=out)
                print(json.dumps(payload, indent=2, default=str)[:8000], file=out)
                print('```', file=out)
            except Exception:
                print(payload, file=out)

        elif kind == 'action':
            print(f"_⚙ auto-pressed: {payload}_", file=out)

        elif kind == 'block':
            for line in payload:
                print(line, file=out)
            print(file=out)

        elif kind == 'kvgrid':
            print('| Metric | Value |', file=out)
            print('| --- | --- |', file=out)
            for label, value in payload:
                print(f"| {_cell(label, 40)} | {_cell(value, 60)} |", file=out)
            print(file=out)

        elif kind == 'metric':
            d = payload
            delta = d.get('delta')
            line = f"**{d['label']}**: {d['value']}"
            if delta:
                line += f"  ({delta})"
            print(line, file=out)

        elif kind == 'table':
            table_no += 1
            if save_data:
                try:
                    df = _to_dataframe(payload)
                    csv_path = os.path.join(out_dir, f'table_{table_no:02d}.csv')
                    df.to_csv(csv_path, index=False)
                    print(f"`{csv_path}`", file=out)
                except Exception:
                    pass
            render_table(payload, max_rows=max_rows, out=out)
            print(file=out)

        elif kind == 'chart':
            chart_no += 1
            if images:
                save_chart(payload, out_dir, chart_no, out)
            else:
                print('```', file=out)
                _render_chart_text(payload['fig'], out)
                print('```', file=out)
            print(file=out)

        elif kind == 'image':
            if isinstance(payload, str) and payload.startswith(('http', '/')):
                print(f"![image]({payload})" if payload.startswith('/') else payload, file=out)

        elif kind.startswith('alert_'):
            print(payload, file=out)

        elif kind == 'traceback':
            if show_tracebacks:
                print('```', file=out)
                print(payload, file=out)
                print('```', file=out)

        elif kind == 'progress':
            pass


def md_to_rl(text: str) -> str:
    """Escape text for reportlab Paragraph, converting the markdown the
    command handlers emit (`**bold**`, `[label](url)`, `` `code` ``)."""
    t = _htmllib.escape(text)
    t = re.sub(r'\[([^\]]+)\]\((https?://[^)\s]+)\)', r'<link href="\2">\1</link>', t)
    t = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', t)
    t = re.sub(r'(?<!\*)\*([^*\n]+)\*(?!\*)', r'<i>\1</i>', t)
    t = re.sub(r'`([^`]+)`', r'<font face="Courier">\1</font>', t)
    return t


def elements_to_sections(elements):
    """Map captured elements onto terminal_pdf section dicts."""
    sections: list = []
    pending_metrics: list = []

    def flush_metrics():
        if pending_metrics:
            sections.append({'type': 'metrics', 'items': list(pending_metrics)})
            pending_metrics.clear()

    for el in elements:
        kind, payload = el['kind'], el.get('payload')
        if kind in ('md', 'caption'):
            flush_metrics()
            text = payload.strip()
            if not text:
                continue
            if text.startswith('# '):
                sections.append({'type': 'heading', 'text': text[2:], 'level': 1})
            elif text.startswith('## '):
                sections.append({'type': 'heading', 'text': text[3:], 'level': 2})
            elif not _NUM_RE.match(text) and len(text) < 110 and text.count('\n') == 0:
                sections.append({'type': 'text', 'text': f'<b>{md_to_rl(text)}</b>'})
            else:
                sections.append({'type': 'text', 'text': md_to_rl(text)})
        elif kind == 'metric':
            pending_metrics.append({'label': str(payload['label']),
                                    'value': str(payload['value']),
                                    'delta': str(payload['delta']) if payload.get('delta') else None})
        elif kind == 'block':
            flush_metrics()
            for line in payload:
                sections.append({'type': 'text', 'text': md_to_rl(line)})
        elif kind == 'kvgrid':
            flush_metrics()
            try:
                import pandas as pd
                sections.append({'type': 'dataframe',
                                 'df': pd.DataFrame(payload, columns=['Metric', 'Value'])})
            except Exception:
                pass
        elif kind == 'action':
            continue
        elif kind == 'code':
            flush_metrics()
            sections.append({'type': 'text', 'text': md_to_rl(f"<pre>{payload}</pre>")})
        elif kind == 'divider':
            flush_metrics()
            sections.append({'type': 'divider'})
        elif kind == 'json':
            flush_metrics()
            sections.append({'type': 'text',
                             'text': md_to_rl(json.dumps(payload, indent=2, default=str)[:4000])})
        elif kind == 'table':
            flush_metrics()
            try:
                sections.append({'type': 'dataframe', 'df': _to_dataframe(payload)})
            except Exception:
                pass
        elif kind == 'chart':
            flush_metrics()
            if not payload.get('mpl'):
                sections.append({'type': 'plotly_fig', 'fig': payload['fig'],
                                 'caption': payload.get('caption', ''),
                                 'height': int(payload.get('height') or 380)})
        elif kind.startswith('alert_'):
            flush_metrics()
            text = re.sub(r'^[^\w]*\s*', '', payload)[:1500]
            sections.append({'type': 'text', 'text': md_to_rl(text)})
    flush_metrics()
    return sections


# ══════════════════════════════════════════════════════════════════════════════
#  3.  Login / API keys
# ══════════════════════════════════════════════════════════════════════════════

ENV_KEY_MAP = {
    'alpha_vantage': ('ALPHA_VANTAGE_API_KEY', 'ALPHAVANTAGE_API_KEY'),
    'fmp':           ('FMP_API_KEY', 'FINANCIALMODELINGPREP_API_KEY'),
    'fred':          ('FRED_API_KEY',),
    'polygon':       ('POLYGON_API_KEY',),
    'newsapi_key':   ('NEWSAPI_KEY', 'NEWS_API_KEY'),
    'finnhub':       ('FINNHUB_API_KEY',),
    'alpaca_key':    ('ALPACA_API_KEY', 'APCA_API_KEY_ID'),
    'alpaca_secret': ('ALPACA_SECRET_KEY', 'APCA_API_SECRET_KEY'),
    'openai_key':    ('OPENAI_API_KEY',),
    'openai_url':    ('OPENAI_BASE_URL', 'OPENAI_API_BASE'),
    'openai_model':  ('OPENAI_MODEL',),
    'gmail_user':    ('GMAIL_USER',),
    'gmail_pass':    ('GMAIL_APP_PASSWORD',),
}


def list_users():
    try:
        with sqlite3.connect(DB_FILE) as conn:
            return conn.execute('SELECT id, email FROM users ORDER BY id').fetchall()
    except Exception:
        return []


def email_for_user(user_id: int):
    try:
        with sqlite3.connect(DB_FILE) as conn:
            row = conn.execute('SELECT email FROM users WHERE id=?', (user_id,)).fetchone()
        return row[0] if row else None
    except Exception:
        return None


def load_session():
    try:
        with open(SESSION_FILE) as fh:
            return json.load(fh)
    except Exception:
        return {}


def save_session(user_id: int, email: str):
    try:
        os.makedirs(os.path.dirname(SESSION_FILE), exist_ok=True)
        with open(SESSION_FILE, 'w') as fh:
            json.dump({'user_id': user_id, 'email': email,
                       'saved_at': datetime.now().isoformat(timespec='seconds')}, fh)
    except Exception:
        pass


def resolve_user(args, interactive_ok: bool):
    """Return (user_id, email, how) using flags → session file → single user."""
    from database import verify_user

    if args.user_id:
        email = email_for_user(args.user_id)
        if not email:
            _die(f"No user with id {args.user_id}.")
        return args.user_id, email, 'flag --user-id'

    if args.email:
        pwd = args.password or os.environ.get('ST_CLI_PASSWORD')
        if pwd is None and interactive_ok and sys.stdin.isatty():
            import getpass
            pwd = getpass.getpass(f"Password for {args.email}: ")
        ok, msg, uid = verify_user(args.email, pwd or '')
        if not ok:
            _die(f"Login failed for {args.email}: {msg}")
        save_session(uid, args.email)
        return uid, args.email, 'password login'

    sess = load_session()
    if sess.get('user_id') and email_for_user(sess['user_id']):
        return sess['user_id'], sess['email'], 'saved session'

    users = list_users()
    if len(users) == 1:
        uid, email = users[0]
        save_session(uid, email)
        return uid, email, 'only user in database'

    if users and interactive_ok and sys.stdin.isatty():
        print("No saved session. Available users:")
        for uid, email in users:
            print(f"  {uid}: {email}")
        try:
            choice = input("User id (or e-mail): ").strip()
        except EOFError:
            choice = ''
        if choice.isdigit() and any(str(u) == choice for u, _ in users):
            uid = int(choice)
            return uid, email_for_user(uid), 'interactive pick'
        if choice:
            import getpass
            ok, msg, uid = verify_user(choice, getpass.getpass(f"Password for {choice}: "))
            if ok:
                save_session(uid, choice)
                return uid, choice, 'interactive login'
            _die(f"Login failed: {msg}")

    if users:
        lines = '\n'.join(f"  {uid}: {email}" for uid, email in users)
        _die("Multiple users found — pick one with --email/--password or --user-id:\n" + lines)
    _die("No users in users.db. Create one through the Streamlit app first.")


def build_api_keys(user_id: int, args) -> tuple[dict, list]:
    """Merge DB keys with a keys file and environment variables. Returns (keys, sources)."""
    from database import get_user_api_keys, KNOWN_SERVICES

    keys = {s: '' for s in KNOWN_SERVICES}
    keys.update({k: '' for k in ('openai_key', 'openai_url', 'openai_model')})
    sources: list = []
    if user_id:
        keys.update(get_user_api_keys(user_id))
        if any(keys.values()):
            sources.append('account')

    if args.keys_file:
        try:
            with open(os.path.expanduser(args.keys_file)) as fh:
                file_keys = json.load(fh)
            for k, v in file_keys.items():
                if v and not keys.get(k):
                    keys[k] = v
            sources.append(f'keys-file({os.path.basename(args.keys_file)})')
        except Exception as e:
            print(f"⚠️  Could not read --keys-file: {e}", file=sys.stderr)

    if not args.no_env_keys:
        used = []
        for key, env_names in ENV_KEY_MAP.items():
            if keys.get(key):
                continue
            for name in env_names:
                if os.environ.get(name):
                    keys[key] = os.environ[name]
                    used.append(key)
                    break
        if used:
            sources.append('env')

    return keys, sources


def _die(msg: str, code: int = 2):
    print(f"❌ {msg}", file=sys.stderr)
    raise SystemExit(code)


# ══════════════════════════════════════════════════════════════════════════════
#  4.  Command execution
# ══════════════════════════════════════════════════════════════════════════════

def seed_session_state(user_id: int, email: str, api_keys: dict):
    from config import SESSION_DEFAULTS

    st = _STUB
    for k, v in SESSION_DEFAULTS.items():
        st.session_state.setdefault(k, v)
    st.session_state['authenticated'] = True
    st.session_state['user_id'] = user_id
    st.session_state['email'] = email
    st.session_state['user_email'] = email
    st.session_state['current_strategy'] = 'TERMINAL'
    st.session_state['term_api_keys'] = dict(api_keys)


def run_command(raw: str, api_keys: dict, tracebacks: bool = False) -> tuple[list, float]:
    """Execute one terminal command; return (captured elements, seconds)."""
    from terminal import parse_and_run_command, cmd_screen, _cmd_search
    from features import cmd_polygon_iv

    del ELEMENTS[:]
    UNKNOWN_APIS.clear()
    head = raw.strip().upper().split()[0] if raw.strip() else ''
    parts = raw.strip().upper().split()
    t0 = time.perf_counter()

    try:
        # Commands with internal widgets are handled by terminal_page, not the parser
        if head == 'SCREEN':
            cmd_screen(api_keys)
        elif head == 'SEARCH':
            _cmd_search(raw.strip()[6:].strip())
        elif head == 'IV':
            cmd_polygon_iv(parts, api_keys)
        else:
            parse_and_run_command(raw, api_keys)
    except (_Rerun, _Stop):
        pass
    except Exception as e:
        _STUB.error(f"Command error: {e}")
        if tracebacks:
            _STUB.exception(e)

    return list(ELEMENTS), time.perf_counter() - t0


# ══════════════════════════════════════════════════════════════════════════════
#  5.  Presentation helpers
# ══════════════════════════════════════════════════════════════════════════════

BANNER = ("📟 **STRATEGY TERMINAL (CLI)** — yfinance · FRED · CoinGecko · GDELT · RSS · "
          "World Bank · Alpha Vantage · FMP · Polygon.io · NewsAPI")


def print_banner(user_id, email, key_sources, out_dir, interactive=False):
    now = datetime.now().strftime('%Y-%m-%d  %H:%M')
    who = f"`{email}`" + (f" (id {user_id})" if user_id else "")
    print(BANNER)
    print(f"👤 {who}  ·  🔑 keys: "
          f"{', '.join(key_sources) if key_sources else 'none'}  ·  🕒 {now}")
    print(f"🗂  output: `{out_dir}`")
    if interactive:
        print("Type a command (`HELP` for the reference, `exit` to quit, "
              "`history` for recent commands).")
    print('\n' + '─' * 78 + '\n')


def print_command_header(cmd: str):
    print(f"### ⌨️  `{cmd.upper()}`")


def write_markdown_report(path: str, command: str, elements, out_dir: str, email: str):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or '.', exist_ok=True)
    import io as _io
    buf = _io.StringIO()
    print(f"# Terminal report — `{command.upper()}`\n", file=buf)
    print(f"_{datetime.now():%Y-%m-%d %H:%M} · {email}_\n", file=buf)
    render_elements(elements, out_dir, out=buf, images=True, max_rows=200)
    with open(path, 'w') as fh:
        fh.write(buf.getvalue())
    return path


def export_pdf(path: str, command: str, elements, email: str):
    from terminal_pdf import generate_terminal_pdf
    sections = elements_to_sections(elements)
    if not sections:
        sections = [{'type': 'text', 'text': 'No output captured.'}]
    pdf = generate_terminal_pdf(
        title=f"Terminal: {command.upper()}",
        sections=sections,
        user_email=email,
        subtitle=f"Command: {command.upper()}  |  {datetime.now():%Y-%m-%d %H:%M}",
    )
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as fh:
        fh.write(pdf)
    return path


def pdf_pages_to_png(pdf_path: str) -> list[str]:
    """Rasterise every page of a PDF so it can be shown inline in chat."""
    from pdf2png import pdf_to_png
    return pdf_to_png(pdf_path, dpi=100)


def open_pdf_in_browser(pdf_path: str) -> bool:
    """Open `pdf_path` in the default browser, falling back to xdg-open."""
    url = pathlib.Path(pdf_path).resolve().as_uri()
    try:
        import webbrowser
        browser = os.environ.get('BROWSER') or None
        opener = webbrowser.get(browser) if browser else webbrowser
        if opener.open(url):
            return True
    except Exception:
        pass
    try:
        import subprocess
        subprocess.Popen(['xdg-open', pdf_path],
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
        return True
    except Exception as e:
        print(f"⚠️  could not open the PDF: {e}", file=sys.stderr)
        return False


def flush_downloads(out_dir: str):
    """Persist anything the command offered through st.download_button."""
    written = []
    for label, (file_name, data) in DOWNLOAD_FILES.items():
        try:
            path = os.path.join(out_dir, os.path.basename(file_name) or 'download.bin')
            mode = 'wb'
            payload = data
            if isinstance(data, str):
                mode, payload = 'w', data
            elif isinstance(data, (bytes, bytearray)):
                payload = bytes(data)
            else:                                   # file-like
                payload = data.getvalue() if hasattr(data, 'getvalue') else str(data)
            with open(path, mode) as fh:
                fh.write(payload)
            written.append((label, path))
        except Exception as e:
            print(f"⚠️  Could not save download '{label}': {e}", file=sys.stderr)
    DOWNLOAD_FILES.clear()
    return written


# ══════════════════════════════════════════════════════════════════════════════
#  6.  Entry points
# ══════════════════════════════════════════════════════════════════════════════

def execute_once(cmd: str, ctx) -> int:
    """Run a single command and render it. Returns 0 on success."""
    if not cmd.strip():
        return 0

    # One folder per command so multi-command runs never overwrite each other's
    # chart_01.png / table_01.csv.
    ctx.n = getattr(ctx, 'n', 0) + 1
    cmd_dir = os.path.join(ctx.out_dir, f"{ctx.n:02d}_{_slug(cmd)}")
    os.makedirs(cmd_dir, exist_ok=True)

    elements, secs = run_command(cmd, ctx.keys, tracebacks=ctx.tracebacks)

    print_command_header(cmd)
    render_elements(elements, cmd_dir, images=ctx.images,
                    max_rows=ctx.max_rows, show_tracebacks=ctx.tracebacks,
                    save_data=ctx.save_data)

    for label, path in flush_downloads(cmd_dir):
        print(f"⬇️  `{label}` → `{path}`")

    if ctx.pdf:
        try:
            pdf_path = export_pdf(ctx.pdf_path or
                                  os.path.join(cmd_dir, f"{_slug(cmd)}.pdf"),
                                  cmd, elements, ctx.email)
            print(f"📄 PDF → `{pdf_path}`")
            if ctx.open_pdf:
                if not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')
                        or os.environ.get('BROWSER')):
                    print("ℹ️  no desktop session (DISPLAY/WAYLAND_DISPLAY/BROWSER unset) — "
                          "PDF left on disk instead")
                elif open_pdf_in_browser(pdf_path):
                    print("🌐 opened the PDF in your browser")
            if ctx.pdf_png:
                for png in pdf_pages_to_png(pdf_path):
                    print(f"![{_slug(cmd)} page]({png})")
                    print(f"`{png}`")
        except Exception as e:
            print(f"⚠️  PDF export failed: {e}", file=sys.stderr)

    if ctx.md:
        try:
            md_path = write_markdown_report(
                ctx.md_path or os.path.join(cmd_dir, f"{_slug(cmd)}.md"),
                cmd, elements, cmd_dir, ctx.email)
            print(f"📝 Report → `{md_path}`")
        except Exception as e:
            print(f"⚠️  Markdown report failed: {e}", file=sys.stderr)

    print(f"_⏱ {secs:.2f}s_")
    print('\n' + '─' * 78 + '\n')

    if ctx.debug and UNKNOWN_APIS:
        print(f"(streamlit APIs stubbed blindly: {sorted(UNKNOWN_APIS)})", file=sys.stderr)
    return 0


def _slug(cmd: str) -> str:
    return re.sub(r'[^a-z0-9]+', '_', cmd.strip().lower()).strip('_') or 'output'


def repl(ctx) -> int:
    history: list[str] = []
    print("Interactive mode — `exit` to quit.")
    while True:
        try:
            raw = input('📟 > ')
        except (EOFError, KeyboardInterrupt):
            print()
            break
        cmd = raw.strip()
        if not cmd:
            continue
        low = cmd.lower()
        if low in ('exit', 'quit', ':q', 'q'):
            break
        if low == 'history':
            for i, h in enumerate(history, 1):
                print(f"{i:3d}  {h}")
            continue
        if low in ('clear', 'cls'):
            print('\033[2J\033[H', end='')
            continue
        if low in ('commands', 'cmds'):
            print_command_reference()
            continue
        history.append(cmd)
        try:
            execute_once(cmd, ctx)
        except Exception as e:
            print(f"❌ Unexpected error: {e}", file=sys.stderr)
            if ctx.tracebacks:
                import traceback
                traceback.print_exc()
    return 0


def print_command_reference():
    try:
        from terminal import COMMAND_SUGGESTIONS
    except Exception as e:
        print(f"Could not load commands: {e}")
        return
    print("```")
    for cmd, desc in COMMAND_SUGGESTIONS:
        print(f"{cmd:<28} {desc}")
    print("```")


def print_help_text():
    try:
        from terminal import COMMAND_HELP
    except Exception:
        COMMAND_HELP = ''
    print(COMMAND_HELP if COMMAND_HELP else 'HELP unavailable.')


def parse_args(argv):
    p = argparse.ArgumentParser(
        prog='app-cli.py',
        description='Command-line front-end for the StrategyTerminal Streamlit app.',
        epilog='examples:\n'
               '  python app-cli.py "AAPL"\n'
               '  python app-cli.py "AAPL GP 1y" "WEI" "VOL TSLA 6mo"\n'
               '  python app-cli.py --email me@example.com --password pw "WL"\n'
               '  python app-cli.py -i\n',
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('command', nargs='*',
                   help='terminal command(s), e.g. "AAPL GP 1y", WEI, NEWS TOP')
    p.add_argument('-c', '--cmd', action='append', default=[], dest='cmd',
                   help='command to run (repeatable, same as positional)')
    p.add_argument('--user-id', type=int, help='use this user id (skips password)')
    p.add_argument('--email', help='login e-mail')
    p.add_argument('--password', help='login password (or ST_CLI_PASSWORD env var)')
    p.add_argument('--anonymous', '--no-login', action='store_true',
                   help='run without a user (market data works; WL/PNL/PORT/alerts need a login)')
    p.add_argument('--list-users', action='store_true', help='list users in users.db')
    p.add_argument('--keys-file', help='JSON file of API keys to merge (DB keys win)')
    p.add_argument('--no-env-keys', action='store_true',
                   help='ignore *_API_KEY environment variables')
    p.add_argument('--out-dir', help='directory for PNGs/CSV/PDF (default cli_out/<ts>)')
    p.add_argument('--max-rows', type=int, default=60, help='max table rows (default 60)')
    p.add_argument('--no-images', action='store_true',
                   help='do not export charts as PNG — print text summaries instead')
    p.add_argument('--no-save-data', action='store_true',
                   help='do not write captured tables to CSV')
    p.add_argument('--pdf', action='store_true',
                   help='also export the output as PDF (default cli_out/<ts>/<cmd>.pdf)')
    p.add_argument('--pdf-path', help='PDF output path (implies --pdf)')
    p.add_argument('--pdf-png', action='store_true',
                   help='also rasterise the exported PDF to PNG so it can be viewed inline')
    p.add_argument('--open-pdf', action='store_true',
                   help='open the exported PDF in the desktop viewer (default when --pdf is used)')
    p.add_argument('--no-open-pdf', action='store_true',
                   help='do not launch a viewer for the exported PDF')
    p.add_argument('--md', action='store_true',
                   help='also write the output as a markdown report')
    p.add_argument('--md-path', help='markdown report path (implies --md)')
    p.add_argument('--press', action='append', default=[], metavar='LABEL',
                   help='force-press a button with this label (repeatable)')
    p.add_argument('--no-autopress', action='store_true',
                   help='never auto-press Run/Apply buttons')
    p.add_argument('--tracebacks', action='store_true', help='show python tracebacks')
    p.add_argument('--debug', action='store_true', help='show stubbed-API warnings')
    p.add_argument('--no-cache', action='store_true', help='disable data caching')
    p.add_argument('-i', '--interactive', action='store_true', help='interactive REPL')
    p.add_argument('--list-commands', action='store_true',
                   help='print the terminal command reference and exit')
    p.add_argument('--help-text', action='store_true',
                   help='print the built-in HELP page and exit')
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])

    if args.no_cache:
        os.environ['ST_CLI_NO_CACHE'] = '1'

    FORCED_PRESSED.update(lbl.strip() for lbl in args.press if lbl.strip())
    if args.no_autopress:
        # Make the auto-press pattern match nothing
        globals()['_AUTOPRESS_RE'] = re.compile(r'(?!x)x')

    if args.list_commands:
        print_command_reference()
        return 0
    if args.help_text:
        print_help_text()
        return 0
    if args.list_users:
        users = list_users()
        print('\n'.join(f"{uid}\t{email}" for uid, email in users) or '(no users)')
        return 0

    from database import init_database
    init_database()

    commands = list(args.command) + list(args.cmd)

    # Commands from stdin when piped and nothing was passed
    if not commands and not args.interactive and not sys.stdin.isatty():
        commands = [ln.strip() for ln in sys.stdin
                    if ln.strip() and not ln.strip().startswith('#')]

    interactive = args.interactive or (not commands)

    if args.anonymous:
        user_id, email, how = None, '(anonymous)', '--anonymous'
    else:
        user_id, email, how = resolve_user(args, interactive_ok=interactive)
    keys, sources = build_api_keys(user_id, args)
    out_dir = args.out_dir or os.path.join(
        DEFAULT_OUT_ROOT, datetime.now().strftime('%Y%m%d-%H%M%S'))
    out_dir = os.path.abspath(os.path.expanduser(out_dir))
    os.makedirs(out_dir, exist_ok=True)

    seed_session_state(user_id, email, keys)

    ctx = types.SimpleNamespace(
        keys=keys, email=email, user_id=user_id, out_dir=out_dir,
        images=not args.no_images, max_rows=args.max_rows,
        save_data=not args.no_save_data, tracebacks=args.tracebacks,
        pdf=args.pdf or bool(args.pdf_path), md=args.md or bool(args.md_path),
        pdf_path=args.pdf_path, md_path=args.md_path, pdf_png=args.pdf_png,
        # Opening the real PDF in a viewer is the default whenever a PDF is
        # produced — that is the only way to actually "display" a PDF.
        open_pdf=(args.open_pdf or bool(args.pdf) or bool(args.pdf_path))
                 and not args.no_open_pdf,
        debug=args.debug)

    print_banner(user_id, email, sources, out_dir, interactive=False)
    if how:
        print(f"_session: {how}_\n")

    try:
        if commands:
            for cmd in commands:
                execute_once(cmd, ctx)
            if args.interactive:
                return repl(ctx)
            return 0
        return repl(ctx)
    except KeyboardInterrupt:
        print("\n(interrupted)", file=sys.stderr)
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
