"""
config.py – Application constants, colour palette, and shared formatting utilities.
"""
import numpy as np
from reportlab.lib import colors
from reportlab.platypus import TableStyle

# ── Date format ────────────────────────────────────────────────────────────────
DATE_FMT = '%d/%m/%Y'

# ── PDF colour palette ─────────────────────────────────────────────────────────
DARK_HDR   = colors.HexColor('#1a2744')
BLUE_HDR   = colors.HexColor('#1f77b4')
ACCENT     = colors.HexColor('#2563eb')
LIGHT_BLUE = colors.HexColor('#dbeafe')
ROW_ALT    = colors.HexColor('#f1f5f9')
BORDER_CLR = colors.HexColor('#cbd5e1')
POS_CLR    = colors.HexColor('#16a34a')
NEG_CLR    = colors.HexColor('#dc2626')
TEXT_DARK  = colors.HexColor('#0f172a')
TEXT_MID   = colors.HexColor('#475569')

# ── Chart style ────────────────────────────────────────────────────────────────
CHART_STYLE = {
    'strategy':  '#2563eb',
    'benchmark': '#f97316',
    'bg':        '#f8fafc',
    'grid':      '#e2e8f0',
}

# ── Session-state defaults ─────────────────────────────────────────────────────
SESSION_DEFAULTS = dict(
    authenticated=False, user_id=None, email=None, current_strategy='TERMINAL',
    perf_data=None, benchmark_data=None, chart_data=None, stocklist_data=None,
    descriptions=[], date_range={'start': 'N/A', 'end': 'N/A'},
    show_signup=False, show_add_strategy=False, edit_strategy_id=None,
    has_benchmark=False, has_stocklist=False, delete_confirmation=None,
    portfolio_price_df=None, portfolio_ga_result=None, portfolio_strategies=[],
    term_cmd='', term_history=[], term_result=None,
    _cmd_val='', _input_gen=0, _should_run=False,
    term_api_keys=dict(alpha_vantage='', fmp='', fred='', polygon='', openai_key='',
                       openai_url='', openai_model='',
                       alpaca_key='', alpaca_secret='',
                       gmail_user='', gmail_pass='',
                       newsapi_key='', finnhub=''),
    chat_model='', chat_provider='local',
    chat_local_url='http://localhost:11434', chat_local_model='', chat_local_models=[],
    chat_remote_url='http://your-remote-service/v1', chat_remote_model='', chat_remote_models=[],
    chat_history=[], chat_tool_log=[], chat_spark_tickers=[],
    ds_priority={},
    msg_view='inbox', msg_open_id=None, msg_open_msg=None, msg_prefill={},
    msg_compose_gen=0,
)

def _tbl_style(extra=None, n_rows=0):
    """Zebra-striped table with navy header and subtle borders."""
    base = [
        # Header
        ('BACKGROUND',    (0, 0), (-1,  0), DARK_HDR),
        ('TEXTCOLOR',     (0, 0), (-1,  0), colors.white),
        ('FONTNAME',      (0, 0), (-1,  0), 'Helvetica-Bold'),
        ('FONTSIZE',      (0, 0), (-1,  0), 8.5),
        ('TOPPADDING',    (0, 0), (-1,  0), 9),
        ('BOTTOMPADDING', (0, 0), (-1,  0), 9),
        ('LEFTPADDING',   (0, 0), (-1, -1), 9),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 9),
        # Body font
        ('FONTNAME',      (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE',      (0, 1), (-1, -1), 8.5),
        ('TEXTCOLOR',     (0, 1), (-1, -1), TEXT_DARK),
        ('TOPPADDING',    (0, 1), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 7),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        # Alignment – first col left, rest right
        ('ALIGN',         (0, 0), ( 0, -1), 'LEFT'),
        ('ALIGN',         (1, 0), (-1, -1), 'RIGHT'),
        ('ALIGN',         (0, 0), (-1,  0), 'CENTER'),
        # Borders
        ('LINEBELOW',     (0, 0), (-1,  0), 1.5, DARK_HDR),
        ('LINEBELOW',     (0, 1), (-1, -1), 0.5, BORDER_CLR),
        ('BOX',           (0, 0), (-1, -1), 1,   BORDER_CLR),
        ('ROWBACKGROUNDS',(0, 1), (-1, -1), [colors.white, ROW_ALT]),
    ]
    return TableStyle(base + (extra or []))

def fmt_val(v, metric=''):
    if not isinstance(v, (int, float)) or (isinstance(v, float) and np.isnan(v)):
        return str(v)
    if 'Ratio' in metric:
        return f"{v:.2f}"
    if '%' in metric:
        return f"{v:.1f}%"
    return f"{v:,.1f}"
