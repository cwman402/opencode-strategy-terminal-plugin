"""
features.py – Five new Bloomberg-style terminal features:

  WL      – Watchlist dashboard
  EARN    – Earnings calendar for a ticker or watchlist
  ECAL    – Economic calendar (upcoming macro events)
  PNL     – Portfolio P&L monitor with cost-basis tracking
  CORR    – Return correlation matrix heatmap
"""

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.figure_factory as ff
import streamlit as st
import requests
from datetime import datetime, date, timedelta

# Colour palette (mirrors terminal.py)
T = {
    'bg':     '#0a0e1a',
    'panel':  '#0d1326',
    'border': '#1e3a5f',
    'amber':  '#ffb300',
    'green':  '#00e676',
    'red':    '#ff1744',
    'blue':   '#40c4ff',
    'white':  '#e0e0e0',
    'muted':  '#607d8b',
    'header': '#1a2a4a',
}

try:
    import yfinance as yf
    _YF_OK = True
except ImportError:
    _YF_OK = False


# ── Shared price helper ────────────────────────────────────────────────────────

def _best_price(ticker: str) -> tuple[float | None, str]:
    """Pre-market → regular → prev-close, same logic as alert_scheduler."""
    if not _YF_OK:
        return None, 'unavailable'
    try:
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


def _pct_color(v: float) -> str:
    return T['green'] if v >= 0 else T['red']


def _arrow(v: float) -> str:
    return '▲' if v >= 0 else '▼'


# ══════════════════════════════════════════════════════════════════════════════
# 1. WATCHLIST  (WL)
# ══════════════════════════════════════════════════════════════════════════════

def cmd_wl(parts: list, user_id: int):
    """
    WL               – display watchlist dashboard
    WL ADD AAPL      – add ticker
    WL ADD AAPL Tech – add with label
    WL REMOVE AAPL   – remove ticker
    """
    from database import wl_add, wl_remove, wl_get

    sub = parts[1].upper() if len(parts) > 1 else ''

    if sub == 'ADD':
        if len(parts) < 3:
            st.error("Usage: WL ADD TICKER [label]"); return
        ticker = parts[2].upper()
        label  = ' '.join(parts[3:]) if len(parts) > 3 else ''
        ok, msg = wl_add(user_id, ticker, label)
        if ok:
            st.success(f"✅ {msg}")
            sub = ''   # fall through to show updated list
        else:
            st.error(msg); return

    elif sub == 'REMOVE':
        if len(parts) < 3:
            st.error("Usage: WL REMOVE TICKER"); return
        ticker = parts[2].upper()
        ok, msg = wl_remove(user_id, ticker)
        st.success(f"✅ {msg}") if ok else st.error(msg)
        sub = ''

    # ── Dashboard ──
    items = wl_get(user_id)
    st.markdown("<div class='term-header'>👁️  WATCHLIST</div>", unsafe_allow_html=True)

    if not items:
        st.markdown(
            f"<div class='term-panel'><span style='color:{T['muted']};font-family:monospace'>"
            f"Watchlist is empty. Use <b style='color:{T['amber']}'>WL ADD TICKER</b> to add.</span></div>",
            unsafe_allow_html=True)
        st.caption("Example: `WL ADD AAPL`  |  `WL ADD TSLA EV`  |  `WL REMOVE AAPL`")
        return

    rows = []
    for item in items:
        price, src = _best_price(item['ticker'])
        try:
            fi    = yf.Ticker(item['ticker']).fast_info
            prev  = getattr(fi, 'previous_close', None)
            high  = getattr(fi, 'year_high', None)
            low   = getattr(fi, 'year_low', None)
            mktcap = getattr(fi, 'market_cap', None)
            if price and prev and float(prev) > 0:
                chg_p = (float(price) - float(prev)) / float(prev) * 100
            else:
                chg_p = 0.0
        except:
            prev = chg_p = high = low = mktcap = None

        src_icon = {'pre-market': '🌅', 'regular': '📈', 'prev-close': '🔒'}.get(src, '')

        rows.append({
            'ticker': item['ticker'],
            'label':  item['label'] or '—',
            'price':  price,
            'chg_p':  chg_p,
            'high52': high,
            'low52':  low,
            'mktcap': mktcap,
            'src':    src_icon,
        })

    # Price cards grid (4 per row)
    cols = st.columns(4)
    for i, r in enumerate(rows):
        col = cols[i % 4]
        p    = f"${r['price']:,.4f}" if r['price'] else '—'
        c    = r['chg_p']
        col.markdown(
            f"<div class='term-panel' style='padding:10px;text-align:center'>"
            f"<div style='color:{T['amber']};font-family:monospace;font-weight:bold'>"
            f"{r['ticker']} {r['src']}</div>"
            f"<div style='color:{T['muted']};font-family:monospace;font-size:10px'>{r['label']}</div>"
            f"<div style='color:{T['white']};font-family:monospace;font-size:16px'>{p}</div>"
            f"<div style='color:{_pct_color(c)};font-family:monospace'>"
            f"{_arrow(c)} {c:+.2f}%</div>"
            f"</div>", unsafe_allow_html=True)

    # Summary table
    st.markdown("---")

    def _fmt_cap(v):
        if not v: return '—'
        v = float(v)
        if v >= 1e12: return f"${v/1e12:.2f}T"
        if v >= 1e9:  return f"${v/1e9:.2f}B"
        return f"${v/1e6:.1f}M"

    df_rows = []
    for r in rows:
        df_rows.append({
            'Ticker':   r['ticker'],
            'Label':    r['label'],
            'Price':    f"${r['price']:,.4f}" if r['price'] else '—',
            'Day Chg%': f"{r['chg_p']:+.2f}%" if r['chg_p'] is not None else '—',
            '52W High': f"${float(r['high52']):,.2f}" if r['high52'] else '—',
            '52W Low':  f"${float(r['low52']):,.2f}"  if r['low52']  else '—',
            'Mkt Cap':  _fmt_cap(r['mktcap']),
            'Source':   r['src'],
        })
    st.dataframe(pd.DataFrame(df_rows), use_container_width=True, hide_index=True)

    # 1-month normalised chart for all watchlist tickers
    if len(rows) > 1:
        st.markdown("**1-Month Performance (normalised to 100)**")
        fig = go.Figure()
        COLORS = [T['amber'], T['green'], T['blue'], T['red'],
                  '#ce93d8', '#80cbc4', '#ffcc02', '#ff7043']
        for i, r in enumerate(rows):
            try:
                df = yf.Ticker(r['ticker']).history(period='1mo', interval='1d', auto_adjust=True)
                if not df.empty:
                    norm = 100 * df['Close'] / df['Close'].iloc[0]
                    fig.add_trace(go.Scatter(
                        x=df.index, y=norm, name=r['ticker'],
                        line=dict(color=COLORS[i % len(COLORS)], width=2)))
            except:
                pass
        fig.add_hline(y=100, line_dash='dot', line_color=T['muted'], opacity=0.5)
        fig.update_layout(
            paper_bgcolor=T['bg'], plot_bgcolor=T['panel'],
            font=dict(color=T['white'], family='monospace'),
            height=380, hovermode='x unified',
            legend=dict(orientation='h', y=1.06),
            xaxis=dict(gridcolor=T['border']),
            yaxis=dict(gridcolor=T['border']),
            margin=dict(l=10, r=10, t=30, b=10),
        )
        st.plotly_chart(fig, use_container_width=True)

    st.caption("Commands: `WL ADD TICKER [label]`  |  `WL REMOVE TICKER`")


# ══════════════════════════════════════════════════════════════════════════════
# 2. EARNINGS CALENDAR  (EARN)
# ══════════════════════════════════════════════════════════════════════════════

def cmd_earn(parts: list, user_id: int):
    """
    EARN             – upcoming earnings for watchlist tickers
    EARN AAPL        – earnings detail for a specific ticker
    """
    from database import wl_get

    st.markdown("<div class='term-header'>📅  EARNINGS CALENDAR</div>",
                unsafe_allow_html=True)

    specific = parts[1].upper() if len(parts) > 1 else None

    tickers = [specific] if specific else [w['ticker'] for w in wl_get(user_id)]
    if not tickers:
        st.info("No tickers. Specify one (EARN AAPL) or add to watchlist (WL ADD AAPL).")
        return

    rows = []
    today = date.today()

    for ticker in tickers:
        try:
            t    = yf.Ticker(ticker)
            info = t.info
            cal  = t.calendar

            # Earnings date
            earn_date = None
            if cal is not None and not (hasattr(cal, 'empty') and cal.empty):
                try:
                    if isinstance(cal, pd.DataFrame) and 'Earnings Date' in cal.index:
                        v = cal.loc['Earnings Date'].iloc[0]
                        earn_date = pd.to_datetime(v).date() if pd.notna(v) else None
                    elif isinstance(cal, dict) and 'Earnings Date' in cal:
                        v = cal['Earnings Date']
                        if isinstance(v, (list, tuple)) and v:
                            earn_date = pd.to_datetime(v[0]).date()
                        else:
                            earn_date = pd.to_datetime(v).date()
                except:
                    pass

            if earn_date is None:
                # Try from info dict
                ts = info.get('earningsTimestamp') or info.get('earningsTimestampStart')
                if ts:
                    earn_date = datetime.fromtimestamp(int(ts)).date()

            days_to = (earn_date - today).days if earn_date else None
            eps_est = info.get('forwardEps') or info.get('epsForward')
            eps_act = info.get('trailingEps')
            rev_est = info.get('revenueEstimate') or info.get('totalRevenue')

            rows.append({
                'Ticker':      ticker,
                'Name':        (info.get('shortName') or ticker)[:28],
                'Earn. Date':  str(earn_date) if earn_date else '—',
                'Days Away':   days_to if days_to is not None else 9999,
                'Days Label':  (f"{days_to}d" if days_to and days_to >= 0
                                else ('Today!' if days_to == 0 else '—')),
                'EPS Est':     f"${eps_est:.2f}" if eps_est else '—',
                'EPS Actual':  f"${eps_act:.2f}" if eps_act else '—',
                'Revenue Est': _fmt_large(rev_est),
            })
        except Exception as e:
            rows.append({'Ticker': ticker, 'Name': ticker,
                         'Earn. Date': '—', 'Days Away': 9999, 'Days Label': '—',
                         'EPS Est': '—', 'EPS Actual': '—', 'Revenue Est': '—'})

    rows.sort(key=lambda x: x['Days Away'])

    # Highlight upcoming (within 30 days)
    for r in rows:
        da = r['Days Away']
        if da == 0:
            badge_color = T['red'];   badge = '🔴 TODAY'
        elif 0 < da <= 7:
            badge_color = T['amber']; badge = f"🟡 {da}d"
        elif 0 < da <= 30:
            badge_color = T['green']; badge = f"🟢 {da}d"
        else:
            badge_color = T['muted']; badge = r['Days Label']

        st.markdown(
            f"<div class='term-panel'>"
            f"<span style='color:{T['amber']};font-family:monospace;font-weight:bold;font-size:13px'>"
            f"{r['Ticker']}</span>"
            f"<span style='color:{T['muted']};font-family:monospace;font-size:11px'> — {r['Name']}</span>"
            f"<span style='color:{badge_color};font-family:monospace;font-size:12px;float:right'>"
            f"{badge}</span><br>"
            f"<span style='color:{T['muted']};font-family:monospace;font-size:11px'>"
            f"📅 {r['Earn. Date']} &nbsp;|&nbsp; "
            f"EPS Est: <b style='color:{T['white']}'>{r['EPS Est']}</b> &nbsp;|&nbsp; "
            f"EPS Actual: <b style='color:{T['white']}'>{r['EPS Actual']}</b> &nbsp;|&nbsp; "
            f"Rev Est: <b style='color:{T['white']}'>{r['Revenue Est']}</b>"
            f"</span></div>", unsafe_allow_html=True)

    # For specific ticker: show historical earnings surprise
    if specific:
        try:
            t = yf.Ticker(specific)
            hist_earn = t.earnings_history
            if hist_earn is not None and not hist_earn.empty:
                st.markdown("**Historical EPS Surprise**")
                fig = go.Figure()
                dates = hist_earn.index.astype(str) if hasattr(hist_earn.index, 'astype') else list(range(len(hist_earn)))
                if 'epsEstimate' in hist_earn.columns and 'epsActual' in hist_earn.columns:
                    fig.add_trace(go.Bar(name='EPS Estimate', x=dates,
                        y=hist_earn['epsEstimate'], marker_color=T['muted']))
                    fig.add_trace(go.Bar(name='EPS Actual', x=dates,
                        y=hist_earn['epsActual'], marker_color=T['amber']))
                    fig.update_layout(
                        barmode='group', paper_bgcolor=T['bg'], plot_bgcolor=T['panel'],
                        font=dict(color=T['white'], family='monospace'), height=320,
                        xaxis=dict(gridcolor=T['border']),
                        yaxis=dict(gridcolor=T['border'], title='EPS ($)'),
                        legend=dict(orientation='h'),
                        margin=dict(l=10, r=10, t=30, b=10),
                    )
                    st.plotly_chart(fig, use_container_width=True)
        except:
            pass


def _fmt_large(v):
    if not v: return '—'
    try:
        v = float(v)
        if v >= 1e12: return f"${v/1e12:.2f}T"
        if v >= 1e9:  return f"${v/1e9:.2f}B"
        if v >= 1e6:  return f"${v/1e6:.1f}M"
        return f"${v:,.0f}"
    except:
        return '—'


# ══════════════════════════════════════════════════════════════════════════════
# 3. ECONOMIC CALENDAR  (ECAL)
# ══════════════════════════════════════════════════════════════════════════════

# Static list of major recurring US macro events (supplemented by FRED release dates)
_MAJOR_EVENTS = [
    # (month, day, name, importance)  — approximate typical release windows
    # Fed schedule is dynamic; we show next known FOMC dates via hard-coded 2025-2026 schedule
]

_FOMC_DATES_2025_2026 = [
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18",
    "2025-07-30", "2025-09-17", "2025-11-06", "2025-12-17",
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
    "2026-07-29", "2026-09-16", "2026-11-04", "2026-12-16",
]


def cmd_ecal(api_keys: dict):
    """ECAL — Economic calendar: FOMC dates + FRED release schedule + key macro."""
    st.markdown("<div class='term-header'>📆  ECONOMIC CALENDAR</div>",
                unsafe_allow_html=True)

    today     = date.today()
    lookahead = today + timedelta(days=90)

    events = []

    # ── FOMC dates ──
    for ds in _FOMC_DATES_2025_2026:
        d = date.fromisoformat(ds)
        if today <= d <= lookahead:
            events.append({'Date': d, 'Event': 'FOMC Rate Decision',
                           'Category': 'Central Bank', 'Importance': '🔴 HIGH',
                           'Source': 'Fed', 'Notes': 'Federal Open Market Committee'})

    # ── FRED latest release dates via API ──
    fred_key  = api_keys.get('fred', '')
    fred_series = {
        'CPIAUCSL':          ('CPI (Urban All Items)',          'Inflation',    '🔴 HIGH'),
        'UNRATE':            ('Unemployment Rate',              'Labor',        '🔴 HIGH'),
        'PAYEMS':            ('Non-Farm Payrolls',              'Labor',        '🔴 HIGH'),
        'GDP':               ('GDP (Quarterly)',                'Growth',       '🔴 HIGH'),
        'A191RL1Q225SBEA':   ('Real GDP Growth Rate',          'Growth',       '🔴 HIGH'),
        'RSXFS':             ('Retail Sales ex-Auto',          'Consumer',     '🟡 MED'),
        'INDPRO':            ('Industrial Production',         'Industry',     '🟡 MED'),
        'HOUST':             ('Housing Starts',                'Housing',      '🟡 MED'),
        'T10Y2Y':            ('10Y-2Y Yield Spread',           'Rates',        '🟡 MED'),
        'DCOILWTICO':        ('WTI Crude Oil',                 'Commodities',  '🟢 LOW'),
    }

    for sid, (name, cat, imp) in fred_series.items():
        try:
            params = {'series_id': sid, 'file_type': 'json',
                      'sort_order': 'desc', 'limit': 1}
            if fred_key:
                params['api_key'] = fred_key
            r = requests.get('https://api.stlouisfed.org/fred/series/observations',
                             params=params, timeout=8)
            if r.status_code == 200:
                obs = r.json().get('observations', [])
                if obs:
                    d = date.fromisoformat(obs[0]['date'])
                    # Show if it fell in next 90d window or was recent (last 7d)
                    if d >= today - timedelta(days=7):
                        events.append({'Date': d, 'Event': name, 'Category': cat,
                                       'Importance': imp, 'Source': 'FRED',
                                       'Notes': f"Series: {sid}"})
        except:
            pass

    # ── Always show upcoming FOMC even without FRED ──
    if not events:
        for ds in _FOMC_DATES_2025_2026:
            d = date.fromisoformat(ds)
            if d >= today:
                events.append({'Date': d, 'Event': 'FOMC Rate Decision',
                               'Category': 'Central Bank', 'Importance': '🔴 HIGH',
                               'Source': 'Fed', 'Notes': 'Federal Open Market Committee'})
                if len([e for e in events if 'FOMC' in e['Event']]) >= 3:
                    break

    events.sort(key=lambda x: x['Date'])

    if not events:
        st.info("No upcoming events found. Add a FRED API key in Terminal → API Keys for release dates.")
        return

    # Group by month
    from itertools import groupby
    for month_key, grp in groupby(events, key=lambda x: x['Date'].strftime('%B %Y')):
        st.markdown(
            f"<div style='color:{T['amber']};font-family:monospace;font-weight:bold;"
            f"font-size:12px;margin:10px 0 4px;letter-spacing:1px'>"
            f"── {month_key.upper()} ──</div>", unsafe_allow_html=True)
        for ev in grp:
            days_to = (ev['Date'] - today).days
            if days_to == 0:   day_lbl, day_clr = 'TODAY', T['red']
            elif days_to < 0:  day_lbl, day_clr = f"{abs(days_to)}d ago", T['muted']
            elif days_to <= 7: day_lbl, day_clr = f"in {days_to}d", T['amber']
            else:              day_lbl, day_clr = f"in {days_to}d", T['green']

            st.markdown(
                f"<div class='term-panel' style='padding:8px 14px'>"
                f"<span style='color:{T['white']};font-family:monospace;font-weight:bold'>"
                f"{ev['Date'].strftime('%d %b')} &nbsp;</span>"
                f"<span style='color:{T['amber']};font-family:monospace'>{ev['Event']}</span>"
                f"<span style='color:{day_clr};font-family:monospace;font-size:11px;float:right'>"
                f"{day_lbl}</span><br>"
                f"<span class='term-lbl'>{ev['Importance']} &nbsp;|&nbsp; "
                f"{ev['Category']} &nbsp;|&nbsp; {ev['Notes']}</span>"
                f"</div>", unsafe_allow_html=True)

    st.caption("💡 Add FRED API key in Terminal → API Keys to see exact release dates for economic series.")


# ══════════════════════════════════════════════════════════════════════════════
# 4. P&L MONITOR  (PNL)
# ══════════════════════════════════════════════════════════════════════════════

def cmd_pnl(parts: list, user_id: int):
    """
    PNL                          – show P&L dashboard
    PNL ADD AAPL 100 150.00      – add/update position (qty, cost basis)
    PNL REMOVE AAPL              – remove position
    """
    from database import pnl_add, pnl_remove, pnl_get

    sub = parts[1].upper() if len(parts) > 1 else ''

    if sub == 'ADD':
        # PNL ADD TICKER QTY COST [notes...]
        if len(parts) < 5:
            st.error("Usage: PNL ADD TICKER QUANTITY COST_BASIS [notes]")
            st.caption("Example: `PNL ADD AAPL 100 150.50`"); return
        ticker = parts[2].upper()
        try:
            qty  = float(parts[3])
            cost = float(parts[4])
        except ValueError:
            st.error("Quantity and cost basis must be numbers."); return
        notes = ' '.join(parts[5:]) if len(parts) > 5 else ''
        ok, msg = pnl_add(user_id, ticker, qty, cost, notes)
        st.success(f"✅ {msg}") if ok else st.error(msg)

    elif sub == 'REMOVE':
        if len(parts) < 3:
            st.error("Usage: PNL REMOVE TICKER"); return
        ticker = parts[2].upper()
        ok, msg = pnl_remove(user_id, ticker)
        st.success(f"✅ {msg}") if ok else st.error(msg)

    # ── Dashboard ──
    positions = pnl_get(user_id)
    st.markdown("<div class='term-header'>💼  P&L MONITOR</div>", unsafe_allow_html=True)

    if not positions:
        st.markdown(
            f"<div class='term-panel'><span style='color:{T['muted']};font-family:monospace'>"
            f"No positions. Use <b style='color:{T['amber']}'>PNL ADD TICKER QTY COST</b> to add.</span></div>",
            unsafe_allow_html=True)
        st.caption("Example: `PNL ADD AAPL 100 150.50`  |  `PNL REMOVE AAPL`")
        return

    rows = []
    total_cost = total_value = total_pnl = 0.0

    for pos in positions:
        price, src = _best_price(pos['ticker'])
        qty  = pos['quantity']
        cost = pos['cost_basis']

        if price:
            mkt_value  = price * qty
            cost_value = cost  * qty
            pnl_val    = mkt_value - cost_value
            pnl_pct    = (price - cost) / cost * 100 if cost else 0
            total_cost  += cost_value
            total_value += mkt_value
            total_pnl   += pnl_val
        else:
            mkt_value = cost_value = pnl_val = pnl_pct = None

        src_icon = {'pre-market': '🌅', 'regular': '📈', 'prev-close': '🔒'}.get(src, '')

        rows.append({
            'ticker':     pos['ticker'],
            'qty':        qty,
            'cost':       cost,
            'price':      price,
            'mkt_value':  mkt_value,
            'pnl_val':    pnl_val,
            'pnl_pct':    pnl_pct,
            'notes':      pos['notes'],
            'src':        src_icon,
        })

    # Portfolio summary metrics
    if total_cost > 0:
        total_pnl_pct = (total_value - total_cost) / total_cost * 100
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Cost Basis",    f"${total_cost:,.2f}")
        m2.metric("Market Value",        f"${total_value:,.2f}")
        m3.metric("Unrealised P&L",      f"${total_pnl:,.2f}",
                  delta=f"{total_pnl_pct:+.2f}%")
        m4.metric("Positions",           str(len(rows)))

    st.markdown("---")

    # Position cards
    for r in rows:
        pnl_color = _pct_color(r['pnl_pct'] or 0)
        pnl_str   = (f"${r['pnl_val']:+,.2f} ({r['pnl_pct']:+.2f}%)"
                     if r['pnl_val'] is not None else '—')
        price_str = f"${r['price']:,.4f} {r['src']}" if r['price'] else '—'
        mv_str    = f"${r['mkt_value']:,.2f}" if r['mkt_value'] else '—'

        st.markdown(
            f"<div class='term-panel'>"
            f"<span style='color:{T['amber']};font-family:monospace;font-weight:bold;font-size:14px'>"
            f"{r['ticker']}</span>"
            + (f"<span style='color:{T['muted']};font-size:11px;font-family:monospace'>"
               f" — {r['notes']}</span>" if r['notes'] else "") +
            f"<br>"
            f"<span style='color:{T['muted']};font-family:monospace;font-size:11px'>"
            f"Qty: <b style='color:{T['white']}'>{r['qty']:,.2f}</b> &nbsp;|&nbsp; "
            f"Cost: <b style='color:{T['white']}'>${r['cost']:,.4f}</b> &nbsp;|&nbsp; "
            f"Price: <b style='color:{T['white']}'>{price_str}</b> &nbsp;|&nbsp; "
            f"Mkt Val: <b style='color:{T['white']}'>{mv_str}</b>"
            f"</span><br>"
            f"<span style='color:{pnl_color};font-family:monospace;font-weight:bold'>"
            f"P&L: {pnl_str}</span>"
            f"</div>", unsafe_allow_html=True)

    # Allocation pie chart
    if len(rows) > 1 and all(r['mkt_value'] for r in rows):
        fig_pie = go.Figure(go.Pie(
            labels=[r['ticker'] for r in rows],
            values=[r['mkt_value'] for r in rows],
            hole=0.4,
            marker=dict(colors=[T['amber'], T['green'], T['blue'], T['red'],
                                 '#ce93d8', '#80cbc4', '#ffcc02', '#ff7043']),
            textfont=dict(color=T['white'], family='monospace'),
        ))
        fig_pie.update_layout(
            title='Portfolio Allocation by Market Value',
            paper_bgcolor=T['bg'], font=dict(color=T['white'], family='monospace'),
            height=360, margin=dict(l=10, r=10, t=45, b=10),
            legend=dict(font=dict(color=T['white'])),
        )
        st.plotly_chart(fig_pie, use_container_width=True)

    # P&L bar chart
    if rows:
        labels = [r['ticker'] for r in rows]
        vals   = [r['pnl_pct'] if r['pnl_pct'] is not None else 0 for r in rows]
        colors = [T['green'] if v >= 0 else T['red'] for v in vals]
        fig_bar = go.Figure(go.Bar(
            x=labels, y=vals, marker_color=colors,
            text=[f"{v:+.2f}%" for v in vals], textposition='outside',
        ))
        fig_bar.add_hline(y=0, line_color=T['muted'], opacity=0.5)
        fig_bar.update_layout(
            title='Unrealised P&L by Position (%)',
            paper_bgcolor=T['bg'], plot_bgcolor=T['panel'],
            font=dict(color=T['white'], family='monospace'), height=320,
            xaxis=dict(gridcolor=T['border']),
            yaxis=dict(gridcolor=T['border']),
            margin=dict(l=10, r=10, t=45, b=10),
        )
        st.plotly_chart(fig_bar, use_container_width=True)

    st.caption("Commands: `PNL ADD TICKER QTY COST [notes]`  |  `PNL REMOVE TICKER`")


# ══════════════════════════════════════════════════════════════════════════════
# 5. CORRELATION MATRIX  (CORR)
# ══════════════════════════════════════════════════════════════════════════════

def cmd_corr(parts: list, user_id: int, api_keys: dict):
    """
    CORR                    – correlation of watchlist tickers (1Y)
    CORR AAPL MSFT NVDA     – custom tickers
    CORR AAPL MSFT 6mo      – custom tickers + period
    """
    from database import wl_get

    st.markdown("<div class='term-header'>🔗  CORRELATION MATRIX</div>",
                unsafe_allow_html=True)

    # Parse tickers and optional period from parts[1:]
    valid_periods = {'1mo', '3mo', '6mo', '1y', '2y', '3y', '5y'}
    extra = [p.upper() for p in parts[1:]] if len(parts) > 1 else []
    period = '1y'
    for p in list(extra):
        if p.lower() in valid_periods:
            period = p.lower()
            extra.remove(p)
            break

    tickers = extra if extra else [w['ticker'] for w in wl_get(user_id)]

    if len(tickers) < 2:
        st.info("Need at least 2 tickers. Specify them: `CORR AAPL MSFT NVDA`  "
                "or add tickers to your Watchlist (`WL ADD TICKER`).")
        return

    with st.spinner(f"Fetching {len(tickers)} tickers for period {period}…"):
        period_col = st.columns([1, 3])
        sel_period = period_col[0].selectbox(
            "Period", ['1mo', '3mo', '6mo', '1y', '2y', '3y'],
            index=['1mo', '3mo', '6mo', '1y', '2y', '3y'].index(period)
                  if period in ['1mo', '3mo', '6mo', '1y', '2y', '3y'] else 3,
            key='corr_period')

        price_data = {}
        failed = []
        for ticker in tickers:
            try:
                df = yf.Ticker(ticker).history(
                    period=sel_period, interval='1d', auto_adjust=True)
                if not df.empty and len(df) > 5:
                    price_data[ticker] = df['Close']
                else:
                    failed.append(ticker)
            except:
                failed.append(ticker)

        if failed:
            st.warning(f"Could not fetch: {', '.join(failed)}")

        if len(price_data) < 2:
            st.error("Need at least 2 tickers with valid data."); return

        # Build returns DataFrame and correlation matrix
        prices_df  = pd.DataFrame(price_data).dropna()
        returns_df = prices_df.pct_change().dropna()
        corr_mat   = returns_df.corr()
        labels     = list(corr_mat.columns)
        z          = corr_mat.values

    # ── Heatmap ──
    fig_hm = go.Figure(go.Heatmap(
        z=z, x=labels, y=labels,
        colorscale=[
            [0.0,  '#ff1744'],  # -1  red
            [0.5,  '#1a2a4a'],  #  0  dark neutral
            [1.0,  '#00e676'],  # +1  green
        ],
        zmin=-1, zmax=1,
        text=[[f"{v:.2f}" for v in row] for row in z],
        texttemplate="%{text}",
        textfont=dict(size=11, color=T['white']),
        hovertemplate='%{y} / %{x}: %{z:.4f}<extra></extra>',
        colorbar=dict(
            title=dict(text='Correlation', font=dict(color=T['white'])),
            tickvals=[-1, -0.5, 0, 0.5, 1],
            ticktext=['-1.0', '-0.5', '0.0', '+0.5', '+1.0'],
            tickfont=dict(color=T['white']),
        ),
    ))
    fig_hm.update_layout(
        title=f'Return Correlation Matrix — {sel_period}',
        paper_bgcolor=T['bg'], plot_bgcolor=T['panel'],
        font=dict(color=T['white'], family='monospace'),
        height=max(400, 80 * len(labels)),
        xaxis=dict(side='bottom', gridcolor=T['border']),
        yaxis=dict(autorange='reversed', gridcolor=T['border']),
        margin=dict(l=10, r=10, t=50, b=10),
    )
    st.plotly_chart(fig_hm, use_container_width=True)

    # ── Highest / lowest pairs ──
    pairs = []
    for i in range(len(labels)):
        for j in range(i + 1, len(labels)):
            pairs.append((labels[i], labels[j], z[i][j]))
    pairs.sort(key=lambda x: x[2])

    c1, c2 = st.columns(2)
    c1.markdown("**Most Negatively Correlated (diversifying)**")
    for a, b, v in pairs[:min(5, len(pairs))]:
        c1.markdown(
            f"<span style='color:{T['red']};font-family:monospace'>{a} / {b}: {v:+.3f}</span>",
            unsafe_allow_html=True)

    c2.markdown("**Most Positively Correlated (concentrated)**")
    for a, b, v in reversed(pairs[-min(5, len(pairs)):]):
        c2.markdown(
            f"<span style='color:{T['green']};font-family:monospace'>{a} / {b}: {v:+.3f}</span>",
            unsafe_allow_html=True)

    # ── Normalised return chart for visual context ──
    st.markdown("---")
    st.markdown("**Normalised Price Performance**")
    COLORS = [T['amber'], T['green'], T['blue'], T['red'],
              '#ce93d8', '#80cbc4', '#ffcc02', '#ff7043']
    fig_ret = go.Figure()
    for i, col in enumerate(prices_df.columns):
        norm = 100 * prices_df[col] / prices_df[col].iloc[0]
        fig_ret.add_trace(go.Scatter(
            x=prices_df.index, y=norm, name=col,
            line=dict(color=COLORS[i % len(COLORS)], width=2)))
    fig_ret.add_hline(y=100, line_dash='dot', line_color=T['muted'], opacity=0.5)
    fig_ret.update_layout(
        paper_bgcolor=T['bg'], plot_bgcolor=T['panel'],
        font=dict(color=T['white'], family='monospace'),
        height=350, hovermode='x unified',
        xaxis=dict(gridcolor=T['border']),
        yaxis=dict(gridcolor=T['border'], title='Indexed (100)'),
        legend=dict(orientation='h', y=1.06),
        margin=dict(l=10, r=10, t=20, b=10),
    )
    st.plotly_chart(fig_ret, use_container_width=True)

    st.caption("Usage: `CORR` (watchlist)  |  `CORR AAPL MSFT NVDA`  |  `CORR AAPL MSFT 6mo`")


# ══════════════════════════════════════════════════════════════════════════════
# 6. VOLATILITY DASHBOARD  (VOL)
# ══════════════════════════════════════════════════════════════════════════════

def cmd_vol(parts: list, api_keys: dict):
    """
    VOL          – VIX dashboard + realised vol comparison across sector ETFs
    VOL AAPL     – full vol breakdown: rolling RV, IV, distribution, surface
    VOL AAPL 6mo – specify lookback period
    """
    import math
    from scipy import stats as scipy_stats

    # Parse ticker and optional period
    valid_periods = {'1mo', '3mo', '6mo', '1y', '2y', '3y'}
    ticker = None
    period = '1y'
    for p in parts[1:]:
        if p.lower() in valid_periods:
            period = p.lower()
        else:
            ticker = p.upper()

    st.markdown("<div class='term-header'>📊  VOLATILITY DASHBOARD</div>",
                unsafe_allow_html=True)

    # ── VIX Regime strip ─────────────────────────────────────────────────────
    vix_syms = {
        'VIX Spot':  '^VIX',
        'VIX1D':     '^VIX1D',
        'VIX3M':     '^VIX3M',
        'VVIX':      '^VVIX',
    }
    vcols = st.columns(len(vix_syms))
    for i, (name, sym) in enumerate(vix_syms.items()):
        try:
            fi   = yf.Ticker(sym).fast_info
            last = getattr(fi, 'last_price', None) or getattr(fi, 'previous_close', None)
            prev = getattr(fi, 'previous_close', None)
            if last and prev and float(prev) > 0:
                chg = (float(last) - float(prev)) / float(prev) * 100
                vcols[i].metric(name, f"{float(last):.2f}", delta=f"{chg:+.2f}%")
            elif last:
                vcols[i].metric(name, f"{float(last):.2f}")
            else:
                vcols[i].metric(name, "—")
        except:
            vcols[i].metric(name, "—")

    # VIX term structure line
    vix_term = {}
    for label, sym in [('1D', '^VIX1D'), ('Spot', '^VIX'), ('3M', '^VIX3M')]:
        try:
            fi = yf.Ticker(sym).fast_info
            v  = getattr(fi, 'last_price', None) or getattr(fi, 'previous_close', None)
            if v and float(v) > 0:
                vix_term[label] = float(v)
        except:
            pass

    if len(vix_term) >= 2:
        fig_ts = go.Figure(go.Scatter(
            x=list(vix_term.keys()), y=list(vix_term.values()),
            mode='lines+markers+text',
            line=dict(color=T['amber'], width=2.5),
            marker=dict(size=10, color=T['amber']),
            text=[f"{v:.2f}" for v in vix_term.values()],
            textposition='top center',
            textfont=dict(color=T['white'], size=10),
        ))
        fig_ts.update_layout(
            title='VIX Term Structure',
            paper_bgcolor=T['bg'], plot_bgcolor=T['panel'],
            font=dict(color=T['white'], family='monospace'),
            height=260, xaxis_title='Tenor', yaxis_title='VIX Level',
            xaxis=dict(gridcolor=T['border']),
            yaxis=dict(gridcolor=T['border']),
            margin=dict(l=10, r=10, t=45, b=10),
        )
        st.plotly_chart(fig_ts, use_container_width=True)

    # VIX 1-year history with regime bands
    try:
        df_vix = yf.Ticker('^VIX').history(period='1y', interval='1d', auto_adjust=True)
        if not df_vix.empty:
            fig_vix = go.Figure()
            fig_vix.add_trace(go.Scatter(
                x=df_vix.index, y=df_vix['Close'], name='VIX',
                line=dict(color=T['amber'], width=1.8),
                fill='tozeroy', fillcolor='rgba(255,179,0,0.06)',
            ))
            for lo, hi, lbl, clr, alpha in [
                (0,  12, 'Low Vol',  T['green'],  0.05),
                (12, 20, 'Normal',   T['blue'],   0.04),
                (20, 30, 'Elevated', T['amber'],  0.06),
                (30, 80, 'Extreme',  T['red'],    0.08),
            ]:
                fig_vix.add_hrect(
                    y0=lo, y1=hi, fillcolor=clr, opacity=alpha, line_width=0,
                    annotation_text=lbl,
                    annotation_font=dict(color=clr, size=9, family='monospace'),
                    annotation_position='right')
            fig_vix.update_layout(
                title='VIX — 1 Year History with Regime Bands',
                paper_bgcolor=T['bg'], plot_bgcolor=T['panel'],
                font=dict(color=T['white'], family='monospace'),
                height=320, hovermode='x unified',
                xaxis=dict(gridcolor=T['border']),
                yaxis=dict(gridcolor=T['border'], title='VIX'),
                margin=dict(l=10, r=10, t=45, b=10),
            )
            st.plotly_chart(fig_vix, use_container_width=True)
    except:
        pass

    # ── No ticker: sector ETF realised vol comparison ─────────────────────────
    if not ticker:
        st.markdown("<div class='term-header' style='font-size:12px'>"
                    "📉 30D REALISED VOL — SECTOR ETFs</div>", unsafe_allow_html=True)
        etfs = [
            ('SPY','S&P 500'), ('QQQ','Nasdaq 100'), ('IWM','Russell 2k'),
            ('XLK','Tech'),    ('XLF','Financials'), ('XLE','Energy'),
            ('XLV','Healthcare'), ('XLB','Materials'), ('XLRE','Real Estate'),
        ]
        rv_rows = []
        for sym, name in etfs:
            try:
                df = yf.Ticker(sym).history(period='3mo', interval='1d', auto_adjust=True)
                if len(df) >= 21:
                    rets = df['Close'].pct_change().dropna()
                    rv30 = rets.tail(21).std() * math.sqrt(252) * 100
                    rv90 = rets.std()           * math.sqrt(252) * 100
                    rv_rows.append({
                        'Ticker':    sym,
                        'Name':      name,
                        '30D RV %':  round(rv30, 2),
                        '90D RV %':  round(rv90, 2),
                        'RV Ratio':  round(rv30 / rv90, 2) if rv90 else None,
                    })
            except:
                pass

        if rv_rows:
            df_rv = pd.DataFrame(rv_rows)
            st.dataframe(df_rv, use_container_width=True, hide_index=True)

            fig_rv = go.Figure()
            fig_rv.add_trace(go.Bar(name='30D RV', x=df_rv['Ticker'],
                y=df_rv['30D RV %'], marker_color=T['amber']))
            fig_rv.add_trace(go.Bar(name='90D RV', x=df_rv['Ticker'],
                y=df_rv['90D RV %'], marker_color=T['blue'], opacity=0.7))
            fig_rv.update_layout(
                barmode='group', title='Realised Volatility Comparison (Annualised)',
                paper_bgcolor=T['bg'], plot_bgcolor=T['panel'],
                font=dict(color=T['white'], family='monospace'), height=340,
                xaxis=dict(gridcolor=T['border']),
                yaxis=dict(gridcolor=T['border'], title='Ann. Vol (%)'),
                legend=dict(orientation='h'),
                margin=dict(l=10, r=10, t=45, b=10),
            )
            st.plotly_chart(fig_rv, use_container_width=True)

        st.caption("💡 Specify a ticker for full breakdown: `VOL AAPL`  |  `VOL TSLA 6mo`")
        return

    # ── Ticker-specific full vol analysis ─────────────────────────────────────
    st.markdown(f"<div class='term-header' style='font-size:12px'>"
                f"🎯 {ticker} — VOL ANALYSIS ({period.upper()})</div>",
                unsafe_allow_html=True)

    df = yf.Ticker(ticker).history(period=period, interval='1d', auto_adjust=True)
    if df.empty:
        st.error(f"No price data for {ticker}"); return

    rets = df['Close'].pct_change().dropna()
    n    = len(rets)

    # Rolling RV chart
    rv_windows = [('10D', 10, T['amber']), ('21D', 21, T['green']), ('63D', 63, T['blue'])]
    fig_rv2 = go.Figure()
    for lbl, w, clr in rv_windows:
        if n >= w:
            s = rets.rolling(w).std() * math.sqrt(252) * 100
            fig_rv2.add_trace(go.Scatter(
                x=df.index[1:], y=s.values,
                name=f'{lbl} RV', line=dict(color=clr, width=1.8)))

    # IV dotted line from info
    try:
        iv = yf.Ticker(ticker).info.get('impliedVolatility')
        if iv and float(iv) > 0:
            fig_rv2.add_hline(
                y=float(iv) * 100,
                line=dict(color=T['red'], dash='dot', width=1.5),
                annotation_text=f"30D IV {float(iv)*100:.1f}%",
                annotation_font=dict(color=T['red'], size=10, family='monospace'),
            )
    except:
        pass

    fig_rv2.update_layout(
        title=f'{ticker} Rolling Realised Volatility (Annualised)',
        paper_bgcolor=T['bg'], plot_bgcolor=T['panel'],
        font=dict(color=T['white'], family='monospace'),
        height=360, hovermode='x unified',
        xaxis=dict(gridcolor=T['border']),
        yaxis=dict(gridcolor=T['border'], title='Ann. Vol (%)'),
        legend=dict(orientation='h', y=1.08),
        margin=dict(l=10, r=10, t=50, b=10),
    )
    st.plotly_chart(fig_rv2, use_container_width=True)

    # Vol metrics strip
    if n >= 21:
        rv10  = rets.tail(10).std() * math.sqrt(252) * 100
        rv21  = rets.tail(21).std() * math.sqrt(252) * 100
        rv63  = rets.tail(63).std() * math.sqrt(252) * 100 if n >= 63 else None
        rvFull= rets.std()           * math.sqrt(252) * 100
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("10D RV",       f"{rv10:.1f}%")
        m2.metric("21D RV",       f"{rv21:.1f}%")
        m3.metric("63D RV",       f"{rv63:.1f}%" if rv63 else "—")
        m4.metric(f"{period} RV", f"{rvFull:.1f}%")

    # Returns distribution histogram + normal fit
    st.markdown("---")
    fig_dist = go.Figure()
    fig_dist.add_trace(go.Histogram(
        x=rets * 100, nbinsx=60, name='Daily Returns',
        marker_color=T['amber'], opacity=0.75,
    ))
    mu  = float(rets.mean() * 100)
    sig = float(rets.std()  * 100)
    if sig > 0:
        xs = [mu + sig * i * 0.1 for i in range(-45, 46)]
        ys = [(1 / (sig * math.sqrt(2 * math.pi))) *
              math.exp(-0.5 * ((x - mu) / sig) ** 2) *
              n * (max(rets * 100) - min(rets * 100)) / 60
              for x in xs]
        fig_dist.add_trace(go.Scatter(
            x=xs, y=ys, name='Normal Fit',
            line=dict(color=T['red'], width=2, dash='dot')))
    fig_dist.update_layout(
        title=f'{ticker} Returns Distribution',
        paper_bgcolor=T['bg'], plot_bgcolor=T['panel'],
        font=dict(color=T['white'], family='monospace'),
        height=320, xaxis_title='Daily Return (%)', yaxis_title='Frequency',
        xaxis=dict(gridcolor=T['border']),
        yaxis=dict(gridcolor=T['border']),
        legend=dict(orientation='h'),
        margin=dict(l=10, r=10, t=45, b=10),
    )
    st.plotly_chart(fig_dist, use_container_width=True)

    # Higher moment stats
    sk    = float(scipy_stats.skew(rets))
    ku    = float(scipy_stats.kurtosis(rets))
    var95 = float(np.percentile(rets, 5)  * 100)
    var99 = float(np.percentile(rets, 1)  * 100)
    tail  = rets[rets <= np.percentile(rets, 5)]
    cvar95 = float(tail.mean() * 100) if len(tail) else 0.0

    s1, s2, s3, s4, s5 = st.columns(5)
    s1.metric("Skewness",    f"{sk:.3f}",   help="Negative = left-tail heavy")
    s2.metric("Excess Kurt", f"{ku:.3f}",   help="Positive = fatter tails than normal")
    s3.metric("VaR 95%",     f"{var95:.2f}%", help="Worst daily loss 1-in-20")
    s4.metric("VaR 99%",     f"{var99:.2f}%", help="Worst daily loss 1-in-100")
    s5.metric("CVaR 95%",    f"{cvar95:.2f}%",help="Avg loss beyond VaR 95%")

    # IV surface (calls scatter)
    try:
        t_obj = yf.Ticker(ticker)
        dates = t_obj.options
        if dates and len(dates) >= 2:
            st.markdown("---")
            st.markdown(f"<div class='term-header' style='font-size:12px'>"
                        f"🌊 {ticker} IMPLIED VOLATILITY SURFACE</div>",
                        unsafe_allow_html=True)
            spot  = (t_obj.info.get('currentPrice') or
                     t_obj.info.get('regularMarketPrice') or 0)
            today = pd.Timestamp.now()
            sx, sy, sz = [], [], []

            for exp in dates[:min(7, len(dates))]:
                try:
                    calls = t_obj.option_chain(exp).calls
                    dte   = max(1, (pd.Timestamp(exp) - today).days)
                    if calls is None or calls.empty: continue
                    calls = calls[(calls['impliedVolatility'] > 0) &
                                  (calls['volume'].fillna(0) > 0)]
                    for _, row in calls.iterrows():
                        k = row['strike']
                        iv_val = row['impliedVolatility'] * 100
                        mono = (k - spot) / spot * 100 if spot else 0
                        if abs(mono) <= 30 and 1 < iv_val < 300:
                            sx.append(dte); sy.append(round(mono, 1))
                            sz.append(round(iv_val, 2))
                except:
                    continue

            if len(sx) >= 8:
                fig_surf = go.Figure(go.Scatter3d(
                    x=sx, y=sy, z=sz, mode='markers',
                    marker=dict(
                        size=4,
                        color=sz,
                        colorscale=[[0, T['green']], [0.5, T['amber']], [1, T['red']]],
                        colorbar=dict(
                            title=dict(text='IV (%)', font=dict(color=T['white'])),
                            tickfont=dict(color=T['white']),
                        ),
                        opacity=0.85,
                    ),
                    hovertemplate='DTE: %{x}d<br>Moneyness: %{y:.1f}%<br>IV: %{z:.1f}%<extra></extra>',
                ))
                fig_surf.update_layout(
                    title=f'{ticker} IV Surface (Calls)',
                    paper_bgcolor=T['bg'],
                    font=dict(color=T['white'], family='monospace'),
                    height=500,
                    scene=dict(
                        xaxis=dict(title='DTE', backgroundcolor=T['panel'],
                                   gridcolor=T['border'], color=T['white']),
                        yaxis=dict(title='Moneyness (%)', backgroundcolor=T['panel'],
                                   gridcolor=T['border'], color=T['white']),
                        zaxis=dict(title='IV (%)', backgroundcolor=T['panel'],
                                   gridcolor=T['border'], color=T['white']),
                        bgcolor=T['panel'],
                    ),
                    margin=dict(l=0, r=0, t=50, b=0),
                )
                st.plotly_chart(fig_surf, use_container_width=True)
                st.caption(f"Surface built from {len(sx)} liquid call contracts "
                           f"across {min(7,len(dates))} expiries. "
                           f"Moneyness = (Strike − Spot) / Spot × 100")
    except:
        pass

    st.caption(f"Usage: `VOL` (VIX + sector overview)  |  `VOL AAPL`  |  `VOL TSLA 6mo`")


# ══════════════════════════════════════════════════════════════════════════════
# 7. ANALYST RECOMMENDATIONS  (ANR)
# ══════════════════════════════════════════════════════════════════════════════

def cmd_anr(parts: list):
    """
    ANR AAPL   – analyst ratings, price targets, recommendation history
    """
    if len(parts) < 2:
        st.error("Usage: ANR TICKER  e.g.  ANR AAPL"); return

    ticker = parts[1].upper()
    st.markdown(f"<div class='term-header'>📊  ANR — ANALYST RECOMMENDATIONS: {ticker}</div>",
                unsafe_allow_html=True)

    t    = yf.Ticker(ticker)
    info = t.info

    # ── Consensus summary ─────────────────────────────────────────────────
    rec_key   = info.get('recommendationKey', '—').upper()
    rec_mean  = info.get('recommendationMean')        # 1=Strong Buy … 5=Sell
    n_analyst = info.get('numberOfAnalystOpinions', 0)
    target    = info.get('targetMeanPrice')
    target_hi = info.get('targetHighPrice')
    target_lo = info.get('targetLowPrice')
    cur_price = info.get('currentPrice') or info.get('regularMarketPrice')

    upside = ((target - cur_price) / cur_price * 100) if target and cur_price else None

    rec_color = {
        'STRONG BUY': T['green'], 'BUY': T['green'],
        'HOLD': T['amber'], 'UNDERPERFORM': T['red'], 'SELL': T['red'],
    }.get(rec_key, T['muted'])

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.markdown(
        f"<div class='term-panel' style='text-align:center;padding:12px'>"
        f"<div style='color:{rec_color};font-family:monospace;font-weight:bold;font-size:16px'>"
        f"{rec_key}</div>"
        f"<div class='term-lbl'>Consensus</div></div>", unsafe_allow_html=True)
    m2.metric("Rating Score", f"{rec_mean:.2f}/5" if rec_mean else "—",
              help="1=Strong Buy  2=Buy  3=Hold  4=Underperform  5=Sell")
    m3.metric("# Analysts",    str(n_analyst) if n_analyst else "—")
    m4.metric("Price Target",  f"${target:,.2f}"    if target    else "—")
    m5.metric("Target High",   f"${target_hi:,.2f}" if target_hi else "—")
    m6.metric("Upside",
              f"{upside:+.1f}%" if upside is not None else "—",
              delta=f"{upside:+.1f}%" if upside is not None else None)

    # Target range bar
    if target and target_lo and target_hi and cur_price:
        fig_bar = go.Figure()
        fig_bar.add_trace(go.Bar(
            x=[target_hi - target_lo], base=[target_lo],
            y=['Target Range'], orientation='h',
            marker_color=T['blue'], opacity=0.4, name='Range',
            hovertemplate=f"Low: ${target_lo:.2f}  High: ${target_hi:.2f}<extra></extra>",
        ))
        for val, lbl, clr in [
            (target,    'Consensus',  T['amber']),
            (cur_price, 'Current',    T['green']),
        ]:
            fig_bar.add_vline(x=val, line_color=clr, line_width=2,
                annotation_text=f"{lbl} ${val:.2f}",
                annotation_font=dict(color=clr, size=10, family='monospace'))
        fig_bar.update_layout(
            paper_bgcolor=T['bg'], plot_bgcolor=T['panel'],
            font=dict(color=T['white'], family='monospace'),
            height=130, showlegend=False,
            xaxis=dict(gridcolor=T['border'], title='Price ($)'),
            yaxis=dict(gridcolor=T['border']),
            margin=dict(l=10, r=10, t=20, b=10),
        )
        st.plotly_chart(fig_bar, use_container_width=True)

    # ── Recommendation breakdown (strong buy / buy / hold / sell) ─────────
    try:
        recs = t.recommendations
        if recs is not None and not recs.empty:
            # Newer yfinance returns summary table
            if hasattr(recs, 'columns') and 'strongBuy' in recs.columns:
                latest = recs.iloc[-1]
                cats   = ['strongBuy', 'buy', 'hold', 'underperform', 'sell']
                labels = ['Strong Buy', 'Buy', 'Hold', 'Underperform', 'Sell']
                colors = [T['green'], '#69f0ae', T['amber'], '#ff6d00', T['red']]
                vals   = [latest.get(c, 0) for c in cats]

                fig_pie = go.Figure(go.Pie(
                    labels=labels, values=vals,
                    marker=dict(colors=colors),
                    textfont=dict(color=T['white'], family='monospace'),
                    hole=0.4,
                    hovertemplate='%{label}: %{value} analysts (%{percent})<extra></extra>',
                ))
                fig_pie.update_layout(
                    title='Analyst Breakdown',
                    paper_bgcolor=T['bg'],
                    font=dict(color=T['white'], family='monospace'),
                    height=340, margin=dict(l=10, r=10, t=45, b=10),
                    legend=dict(font=dict(color=T['white'])),
                )
                st.plotly_chart(fig_pie, use_container_width=True)

            # Older yfinance: time-series of rating changes
            elif 'To Grade' in recs.columns or 'toGrade' in recs.columns:
                col_to   = 'To Grade'   if 'To Grade'   in recs.columns else 'toGrade'
                col_firm = 'Firm'       if 'Firm'       in recs.columns else 'firm'
                col_from = 'From Grade' if 'From Grade' in recs.columns else 'fromGrade'
                recs_show = recs[[col_firm, col_from, col_to]].tail(20)
                recs_show.columns = ['Firm', 'From', 'To']
                recs_show.index   = recs_show.index.strftime('%Y-%m-%d') if hasattr(recs_show.index, 'strftime') else recs_show.index
                st.markdown("**Recent Rating Changes**")
                st.dataframe(recs_show, use_container_width=True)
    except:
        pass

    # ── Earnings estimate table ───────────────────────────────────────────
    try:
        rows = []
        for period, key in [
            ('Current Qtr', 'currentQuarterEstimate'),
            ('Next Qtr',    'nextQuarterEstimate'),
            ('Current Yr',  'earningsEstimateCurrentYear'),
            ('Next Yr',     'earningsEstimateNextYear'),
        ]:
            eps = info.get(key)
            rows.append({'Period': period, 'EPS Estimate': f"${eps:.2f}" if eps else '—'})
        if any(r['EPS Estimate'] != '—' for r in rows):
            st.markdown("**EPS Estimates**")
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    except:
        pass

    st.caption("Usage: `ANR AAPL`  |  `ANR TSLA`  |  `ANR NVDA`")


# ══════════════════════════════════════════════════════════════════════════════
# 8. RELATIVE VALUE  (RV) — peer valuation multiples comparison
# ══════════════════════════════════════════════════════════════════════════════

def cmd_rv(parts: list):
    """
    RV AAPL              – AAPL vs default peers (sector auto-detect)
    RV AAPL MSFT GOOGL   – custom peer group
    """
    if len(parts) < 2:
        st.error("Usage: RV TICKER [peer1 peer2 ...]"); return

    ticker = parts[1].upper()
    custom_peers = [p.upper() for p in parts[2:]] if len(parts) > 2 else []

    st.markdown(f"<div class='term-header'>⚖️  RV — RELATIVE VALUE: {ticker}</div>",
                unsafe_allow_html=True)

    # Auto peer groups by sector
    SECTOR_PEERS = {
        'Technology':           ['AAPL','MSFT','GOOGL','META','NVDA','AMZN','AMD','INTC'],
        'Communication Services':['GOOGL','META','NFLX','DIS','T','VZ','CMCSA'],
        'Consumer Cyclical':    ['AMZN','TSLA','HD','MCD','NKE','SBUX','BKNG'],
        'Consumer Defensive':   ['WMT','KO','PG','PEP','COST','PM','MO'],
        'Financial Services':   ['JPM','BAC','GS','MS','WFC','C','BLK','V','MA'],
        'Healthcare':           ['JNJ','UNH','PFE','MRK','ABBV','LLY','TMO'],
        'Energy':               ['XOM','CVX','COP','SLB','EOG','MPC','PSX'],
        'Industrials':          ['CAT','BA','HON','GE','UPS','RTX','DE','MMM'],
        'Basic Materials':      ['LIN','APD','ECL','SHW','FCX','NEM','DOW'],
        'Real Estate':          ['AMT','PLD','CCI','EQIX','PSA','O','SPG'],
        'Utilities':            ['NEE','DUK','SO','D','AEP','EXC','SRE'],
    }

    # Get ticker sector
    try:
        info   = yf.Ticker(ticker).info
        sector = info.get('sector', '')
        peers  = custom_peers or [p for p in SECTOR_PEERS.get(sector, []) if p != ticker][:6]
    except:
        peers  = custom_peers or []

    all_tickers = [ticker] + peers
    if not peers:
        st.warning("Could not determine peers. Specify them: `RV AAPL MSFT GOOGL`")

    MULTIPLES = [
        ('P/E (TTM)',       'trailingPE'),
        ('P/E (Fwd)',       'forwardPE'),
        ('P/S',            'priceToSalesTrailing12Months'),
        ('P/B',            'priceToBook'),
        ('EV/EBITDA',      'enterpriseToEbitda'),
        ('EV/Revenue',     'enterpriseToRevenue'),
        ('PEG Ratio',      'pegRatio'),
        ('Gross Margin %', 'grossMargins'),
        ('Net Margin %',   'profitMargins'),
        ('ROE %',          'returnOnEquity'),
        ('ROA %',          'returnOnAssets'),
        ('Debt/Equity',    'debtToEquity'),
        ('Rev Growth %',   'revenueGrowth'),
        ('EPS Growth %',   'earningsGrowth'),
        ('Div Yield %',    'dividendYield'),
        ('Mkt Cap',        'marketCap'),
    ]

    rows = []
    with st.spinner("Fetching peer data…"):
        for sym in all_tickers:
            try:
                info = yf.Ticker(sym).info
                row  = {'Ticker': sym, 'Name': (info.get('shortName','') or sym)[:20]}
                for lbl, key in MULTIPLES:
                    v = info.get(key)
                    if v is None:
                        row[lbl] = None
                    elif key in ('grossMargins','profitMargins','returnOnEquity',
                                 'returnOnAssets','revenueGrowth','earningsGrowth',
                                 'dividendYield'):
                        row[lbl] = round(float(v) * 100, 2)
                    elif key == 'marketCap':
                        row[lbl] = float(v)
                    else:
                        row[lbl] = round(float(v), 2)
                rows.append(row)
            except:
                rows.append({'Ticker': sym, 'Name': sym})

    if not rows:
        st.error("No data available."); return

    df = pd.DataFrame(rows).set_index('Ticker')

    # Format display df
    def _fmt(col, val):
        if val is None or (isinstance(val, float) and np.isnan(val)):
            return '—'
        if col == 'Mkt Cap':
            v = float(val)
            return f"${v/1e12:.2f}T" if v>=1e12 else f"${v/1e9:.1f}B" if v>=1e9 else f"${v/1e6:.0f}M"
        if col in ('Gross Margin %','Net Margin %','ROE %','ROA %',
                   'Rev Growth %','EPS Growth %','Div Yield %'):
            return f"{val:.1f}%"
        return f"{val:.2f}"

    display_df = df.copy()
    for col in display_df.columns:
        if col != 'Name':
            display_df[col] = display_df[col].apply(lambda v: _fmt(col, v))

    st.markdown("**Valuation & Fundamental Multiples**")
    st.dataframe(display_df, use_container_width=True)

    # Bar charts for key multiples
    chart_cols = ['P/E (TTM)', 'P/E (Fwd)', 'EV/EBITDA', 'P/S']
    avail = [c for c in chart_cols if c in df.columns]
    if avail:
        fig_rv = go.Figure()
        COLORS = [T['amber'], T['green'], T['blue'], T['red'],
                  '#ce93d8', '#80cbc4', '#ffcc02', '#ff7043']
        for i, sym in enumerate(df.index):
            vals = [df.loc[sym, c] if c in df.columns else None for c in avail]
            fig_rv.add_trace(go.Bar(
                name=sym, x=avail, y=vals,
                marker_color=COLORS[i % len(COLORS)],
            ))
        fig_rv.update_layout(
            barmode='group', title='Key Valuation Multiples',
            paper_bgcolor=T['bg'], plot_bgcolor=T['panel'],
            font=dict(color=T['white'], family='monospace'), height=380,
            xaxis=dict(gridcolor=T['border']),
            yaxis=dict(gridcolor=T['border']),
            legend=dict(orientation='h', y=1.08),
            margin=dict(l=10, r=10, t=50, b=10),
        )
        st.plotly_chart(fig_rv, use_container_width=True)

    # Margin comparison
    margin_cols = ['Gross Margin %', 'Net Margin %', 'ROE %']
    avail_m = [c for c in margin_cols if c in df.columns]
    if avail_m:
        fig_m = go.Figure()
        for i, sym in enumerate(df.index):
            vals = [df.loc[sym, c] if c in df.columns else None for c in avail_m]
            fig_m.add_trace(go.Bar(
                name=sym, x=avail_m, y=vals,
                marker_color=COLORS[i % len(COLORS)],
            ))
        fig_m.update_layout(
            barmode='group', title='Profitability Comparison (%)',
            paper_bgcolor=T['bg'], plot_bgcolor=T['panel'],
            font=dict(color=T['white'], family='monospace'), height=340,
            xaxis=dict(gridcolor=T['border']),
            yaxis=dict(gridcolor=T['border'], title='%'),
            legend=dict(orientation='h', y=1.08),
            margin=dict(l=10, r=10, t=50, b=10),
        )
        st.plotly_chart(fig_m, use_container_width=True)

    st.caption(f"Sector: {sector or '—'}  |  Peers auto-detected. Usage: `RV AAPL`  |  `RV AAPL MSFT GOOGL`")


# ══════════════════════════════════════════════════════════════════════════════
# 9. IPO CALENDAR  (IPO)
# ══════════════════════════════════════════════════════════════════════════════

def cmd_ipo(api_keys: dict):
    """IPO — upcoming & recent IPOs via public sources."""
    st.markdown("<div class='term-header'>🚀  IPO CALENDAR</div>", unsafe_allow_html=True)

    # Try FMP API for IPO calendar
    fmp_key = api_keys.get('fmp', '')
    ipos = []

    if fmp_key:
        try:
            import datetime as _dt
            today     = _dt.date.today()
            from_date = str(today - _dt.timedelta(days=30))
            to_date   = str(today + _dt.timedelta(days=90))
            r = __import__('requests').get(
                'https://financialmodelingprep.com/api/v3/ipo_calendar',
                params={'from': from_date, 'to': to_date, 'apikey': fmp_key},
                timeout=10)
            if r.status_code == 200:
                ipos = r.json()
        except:
            pass

    if ipos:
        import datetime as _dt
        today = _dt.date.today()
        rows  = []
        for ipo in ipos[:40]:
            try:
                d = _dt.date.fromisoformat(ipo.get('date',''))
                days = (d - today).days
                rows.append({
                    'Date':     str(d),
                    'Company':  ipo.get('company','—')[:30],
                    'Symbol':   ipo.get('symbol','—'),
                    'Exchange': ipo.get('exchange','—'),
                    'Price Lo': f"${ipo['priceRange'].split('-')[0].strip()}" if ipo.get('priceRange') and '-' in str(ipo.get('priceRange','')) else '—',
                    'Price Hi': f"${ipo['priceRange'].split('-')[1].strip()}" if ipo.get('priceRange') and '-' in str(ipo.get('priceRange','')) else '—',
                    'Shares':   _fmt_large(ipo.get('shares',0)) if ipo.get('shares') else '—',
                    'Status':   '✅ Priced' if days < 0 else ('🔴 Today' if days==0 else f'🟡 {days}d'),
                })
            except:
                pass

        rows.sort(key=lambda x: x['Date'])
        df_ipo = pd.DataFrame(rows)
        # Split upcoming vs recent
        upcoming = df_ipo[~df_ipo['Status'].str.startswith('✅')]
        recent   = df_ipo[df_ipo['Status'].str.startswith('✅')]

        if not upcoming.empty:
            st.markdown("**📅 Upcoming IPOs**")
            st.dataframe(upcoming, use_container_width=True, hide_index=True)
        if not recent.empty:
            st.markdown("**✅ Recent IPOs (last 30 days)**")
            st.dataframe(recent.tail(15), use_container_width=True, hide_index=True)

    else:
        st.info("📡 Live IPO data requires a **FMP API key** (free tier works). "
                "Add it in Terminal → API Keys.")
        st.markdown("---")
        st.markdown("**Notable Recent & Upcoming IPOs** *(static snapshot)*")

        # Static fallback with well-known recent names
        static = [
            {'Company': 'Reddit',       'Symbol': 'RDDT', 'Status': '✅ Listed Mar 2024',  'Exchange': 'NYSE'},
            {'Company': 'Astera Labs',  'Symbol': 'ALAB', 'Status': '✅ Listed Mar 2024',  'Exchange': 'NASDAQ'},
            {'Company': 'Rubrik',       'Symbol': 'RBRK', 'Status': '✅ Listed Apr 2024',  'Exchange': 'NYSE'},
            {'Company': 'Ibotta',       'Symbol': 'IBTA', 'Status': '✅ Listed Apr 2024',  'Exchange': 'NYSE'},
            {'Company': 'OneStream',    'Symbol': 'OS',   'Status': '✅ Listed Jul 2024',  'Exchange': 'NASDAQ'},
            {'Company': 'Cerebras',     'Symbol': 'CBRS', 'Status': '🟡 Filed 2025',       'Exchange': 'NASDAQ'},
            {'Company': 'Klarna',       'Symbol': 'KLAR', 'Status': '🟡 Expected 2025',    'Exchange': 'NYSE'},
            {'Company': 'Chime',        'Symbol': '—',    'Status': '🟡 Expected 2025',    'Exchange': 'TBD'},
            {'Company': 'Medline',      'Symbol': '—',    'Status': '🟡 Expected 2025',    'Exchange': 'TBD'},
            {'Company': 'StubHub',      'Symbol': '—',    'Status': '🟡 Expected 2025',    'Exchange': 'TBD'},
        ]
        st.dataframe(pd.DataFrame(static), use_container_width=True, hide_index=True)
        st.caption("💡 Add FMP API key for live dates, price ranges, and share counts.")

    st.caption("Usage: `IPO`  |  Add FMP API key for live data")


# ══════════════════════════════════════════════════════════════════════════════
# 10. INSIDER TRANSACTIONS  (INSIDER)
# ══════════════════════════════════════════════════════════════════════════════

def cmd_insider(parts: list):
    """INSIDER AAPL — recent insider buying/selling."""
    if len(parts) < 2:
        st.error("Usage: INSIDER TICKER  e.g.  INSIDER AAPL"); return

    ticker = parts[1].upper()
    st.markdown(f"<div class='term-header'>🔍  INSIDER TRANSACTIONS: {ticker}</div>",
                unsafe_allow_html=True)

    try:
        t       = yf.Ticker(ticker)
        insiders = t.insider_transactions
        insider_holders = t.insider_purchases

        if insiders is None or (hasattr(insiders, 'empty') and insiders.empty):
            st.info("No insider transaction data available for this ticker.")
            return

        df = insiders.copy()
        # Normalise column names
        df.columns = [c.strip() for c in df.columns]

        # Summary buy vs sell
        buy_mask  = df.get('Transaction', df.get('transaction', pd.Series(dtype=str))).str.contains(
            'Purchase|Buy|Acquisition', case=False, na=False)
        sell_mask = df.get('Transaction', df.get('transaction', pd.Series(dtype=str))).str.contains(
            'Sale|Sell|Disposition', case=False, na=False)

        total_buy  = df[buy_mask].get('Value', df[buy_mask].get('value', pd.Series(dtype=float))).sum() if buy_mask.any() else 0
        total_sell = df[sell_mask].get('Value', df[sell_mask].get('value', pd.Series(dtype=float))).sum() if sell_mask.any() else 0

        m1, m2, m3 = st.columns(3)
        m1.metric("Buy Value (90d)",  _fmt_large(total_buy)  if total_buy  else "—",
                  delta="Bullish signal" if total_buy > total_sell else None)
        m2.metric("Sell Value (90d)", _fmt_large(total_sell) if total_sell else "—")
        m3.metric("Net Flow",
                  _fmt_large(abs(total_buy - total_sell)) if (total_buy or total_sell) else "—",
                  delta="Net Buy" if total_buy > total_sell else "Net Sell")

        # Buy/sell donut
        if total_buy or total_sell:
            fig_ins = go.Figure(go.Pie(
                labels=['Insider Buys', 'Insider Sells'],
                values=[total_buy, total_sell],
                hole=0.5,
                marker=dict(colors=[T['green'], T['red']]),
                textfont=dict(color=T['white'], family='monospace'),
            ))
            fig_ins.update_layout(
                title='Insider Buy vs Sell (90d)',
                paper_bgcolor=T['bg'],
                font=dict(color=T['white'], family='monospace'),
                height=300, margin=dict(l=10, r=10, t=45, b=10),
                legend=dict(font=dict(color=T['white'])),
            )
            st.plotly_chart(fig_ins, use_container_width=True)

        # Transaction table — show last 25
        st.markdown("**Recent Insider Transactions**")
        show_cols = [c for c in df.columns if c.lower() in
                     ('insider','name','relation','transaction','startdate','date',
                      'shares','value','text')]
        disp = df[show_cols].head(25) if show_cols else df.head(25)
        if hasattr(disp.index, 'strftime'):
            disp.index = disp.index.strftime('%Y-%m-%d')
        st.dataframe(disp, use_container_width=True)

    except Exception as e:
        st.error(f"Could not load insider data: {e}")

    st.caption("Usage: `INSIDER AAPL`  |  `INSIDER TSLA`")


# ══════════════════════════════════════════════════════════════════════════════
# 11. SHORT INTEREST  (SHORT)
# ══════════════════════════════════════════════════════════════════════════════

def cmd_short(parts: list):
    """SHORT AAPL — short interest, days to cover, borrow rate."""
    if len(parts) < 2:
        st.error("Usage: SHORT TICKER  e.g.  SHORT AAPL"); return

    ticker = parts[1].upper()
    st.markdown(f"<div class='term-header'>📉  SHORT INTEREST: {ticker}</div>",
                unsafe_allow_html=True)

    try:
        t    = yf.Ticker(ticker)
        info = t.info

        short_pct   = info.get('shortPercentOfFloat')
        short_ratio = info.get('shortRatio')          # days to cover
        shares_short= info.get('sharesShort')
        short_prev  = info.get('sharesShortPriorMonth')
        float_shrs  = info.get('floatShares')
        shares_out  = info.get('sharesOutstanding')

        # Change vs prior month
        chg = ((shares_short - short_prev) / short_prev * 100
               if shares_short and short_prev and short_prev > 0 else None)

        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Short % Float",
                  f"{short_pct*100:.2f}%" if short_pct else "—",
                  help="% of float currently sold short")
        m2.metric("Days to Cover",
                  f"{short_ratio:.1f}d"   if short_ratio else "—",
                  help="Shares short / avg daily volume")
        m3.metric("Shares Short",
                  _fmt_large(shares_short) if shares_short else "—")
        m4.metric("vs Prior Month",
                  f"{chg:+.1f}%" if chg is not None else "—",
                  delta=f"{chg:+.1f}%" if chg is not None else None)
        m5.metric("Float",
                  _fmt_large(float_shrs)  if float_shrs  else "—")

        # Squeeze risk gauge
        if short_pct and short_ratio:
            sp   = float(short_pct) * 100
            dtc  = float(short_ratio)
            risk = min(100, int((sp / 20) * 50 + (dtc / 10) * 50))
            risk_color = T['green'] if risk < 30 else T['amber'] if risk < 60 else T['red']
            risk_label = 'LOW' if risk < 30 else 'MODERATE' if risk < 60 else 'HIGH ⚠️'

            st.markdown("---")
            st.markdown("**Short Squeeze Risk Indicator**")
            fig_g = go.Figure(go.Indicator(
                mode="gauge+number",
                value=risk,
                title=dict(text=f"Squeeze Risk: {risk_label}",
                           font=dict(color=T['white'], family='monospace')),
                gauge=dict(
                    axis=dict(range=[0, 100], tickcolor=T['white'],
                              tickfont=dict(color=T['white'])),
                    bar=dict(color=risk_color),
                    steps=[
                        dict(range=[0,  30], color='#1a2a4a'),
                        dict(range=[30, 60], color='#2a3a0a'),
                        dict(range=[60,100], color='#3a1a0a'),
                    ],
                    threshold=dict(line=dict(color=T['red'], width=3),
                                   thickness=0.8, value=70),
                ),
                number=dict(suffix="%", font=dict(color=T['white'], family='monospace')),
            ))
            fig_g.update_layout(
                paper_bgcolor=T['bg'],
                font=dict(color=T['white'], family='monospace'),
                height=300, margin=dict(l=30, r=30, t=60, b=10),
            )
            st.plotly_chart(fig_g, use_container_width=True)
            st.caption(f"Squeeze Risk: Short Float {sp:.1f}%  |  Days to Cover {dtc:.1f}d  |  "
                       f"Score = {risk}/100 (>60 = elevated squeeze potential)")

        # Historical short interest from yfinance
        try:
            si_hist = t.get_info()  # fallback already have info
        except:
            pass

    except Exception as e:
        st.error(f"Could not load short data: {e}")

    st.caption("Usage: `SHORT AAPL`  |  `SHORT GME`  |  `SHORT TSLA`")


# ══════════════════════════════════════════════════════════════════════════════
# 12. TOTAL RETURN ANALYSIS  (TRA)
# ══════════════════════════════════════════════════════════════════════════════

def cmd_tra(parts: list):
    """
    TRA AAPL          – total return vs SPY benchmark
    TRA AAPL SPY QQQ  – custom benchmarks
    TRA AAPL 3y       – custom period
    """
    if len(parts) < 2:
        st.error("Usage: TRA TICKER [benchmark...] [period]"); return

    import math

    valid_periods = {'1mo','3mo','6mo','1y','2y','3y','5y','10y'}
    ticker   = parts[1].upper()
    extra    = [p.upper() for p in parts[2:]]
    period   = '3y'
    benches  = []
    for e in extra:
        if e.lower() in valid_periods:
            period = e.lower()
        else:
            benches.append(e)
    if not benches:
        benches = ['SPY', 'QQQ']

    st.markdown(f"<div class='term-header'>📈  TRA — TOTAL RETURN ANALYSIS: {ticker}</div>",
                unsafe_allow_html=True)

    all_syms  = [ticker] + benches
    COLORS    = [T['amber'], T['green'], T['blue'], T['red'], '#ce93d8', '#80cbc4']
    price_data = {}

    with st.spinner("Loading return data…"):
        for sym in all_syms:
            try:
                df = yf.Ticker(sym).history(period=period, interval='1d',
                                             auto_adjust=True, actions=True)
                if not df.empty:
                    price_data[sym] = df
            except:
                pass

    if ticker not in price_data:
        st.error(f"No data for {ticker}"); return

    # ── Cumulative total return chart (price + dividends reinvested) ──────
    fig_tr = go.Figure()
    stats_rows = []
    for i, sym in enumerate(all_syms):
        if sym not in price_data: continue
        df    = price_data[sym]
        close = df['Close']
        divs  = df.get('Dividends', pd.Series(0, index=df.index))

        # Reinvested dividends: compound factor
        total_ret = 100 * close / close.iloc[0]

        rets    = close.pct_change().dropna()
        ann_ret = (close.iloc[-1] / close.iloc[0]) ** (252 / max(len(close), 1)) - 1
        ann_vol = rets.std() * math.sqrt(252)
        sharpe  = ann_ret / ann_vol if ann_vol > 0 else 0
        mdd     = _max_drawdown(close)
        total   = (close.iloc[-1] / close.iloc[0] - 1) * 100

        stats_rows.append({
            'Symbol':       sym,
            'Total Return': f"{total:+.1f}%",
            'Ann. Return':  f"{ann_ret*100:+.1f}%",
            'Ann. Vol':     f"{ann_vol*100:.1f}%",
            'Sharpe':       f"{sharpe:.2f}",
            'Max DD':       f"{mdd*100:.1f}%",
            'Start':        close.index[0].strftime('%Y-%m-%d'),
            'End':          close.index[-1].strftime('%Y-%m-%d'),
        })

        fig_tr.add_trace(go.Scatter(
            x=close.index, y=total_ret,
            name=sym,
            line=dict(color=COLORS[i % len(COLORS)], width=2.5 if sym==ticker else 1.5),
        ))

    fig_tr.add_hline(y=100, line_dash='dot', line_color=T['muted'], opacity=0.5)
    fig_tr.update_layout(
        title=f'Total Return — {period.upper()} (Base 100)',
        paper_bgcolor=T['bg'], plot_bgcolor=T['panel'],
        font=dict(color=T['white'], family='monospace'),
        height=400, hovermode='x unified',
        xaxis=dict(gridcolor=T['border']),
        yaxis=dict(gridcolor=T['border'], title='Indexed Return'),
        legend=dict(orientation='h', y=1.08),
        margin=dict(l=10, r=10, t=50, b=10),
    )
    st.plotly_chart(fig_tr, use_container_width=True)

    # Stats table
    st.markdown("**Performance Statistics**")
    st.dataframe(pd.DataFrame(stats_rows), use_container_width=True, hide_index=True)

    # ── Rolling 1Y return chart ────────────────────────────────────────────
    fig_roll = go.Figure()
    for i, sym in enumerate(all_syms):
        if sym not in price_data: continue
        close = price_data[sym]['Close']
        roll  = close.pct_change(252) * 100  # 252-day rolling return
        fig_roll.add_trace(go.Scatter(
            x=close.index, y=roll,
            name=f"{sym} 1Y Roll",
            line=dict(color=COLORS[i % len(COLORS)], width=1.8),
        ))
    fig_roll.add_hline(y=0, line_color=T['muted'], opacity=0.5)
    fig_roll.update_layout(
        title='Rolling 1-Year Return (%)',
        paper_bgcolor=T['bg'], plot_bgcolor=T['panel'],
        font=dict(color=T['white'], family='monospace'),
        height=320, hovermode='x unified',
        xaxis=dict(gridcolor=T['border']),
        yaxis=dict(gridcolor=T['border'], title='1Y Return (%)'),
        legend=dict(orientation='h', y=1.08),
        margin=dict(l=10, r=10, t=50, b=10),
    )
    st.plotly_chart(fig_roll, use_container_width=True)

    # ── Drawdown chart ─────────────────────────────────────────────────────
    fig_dd = go.Figure()
    for i, sym in enumerate(all_syms):
        if sym not in price_data: continue
        close = price_data[sym]['Close']
        peak  = close.cummax()
        dd    = (close - peak) / peak * 100
        fig_dd.add_trace(go.Scatter(
            x=close.index, y=dd,
            name=f"{sym} DD",
            line=dict(color=COLORS[i % len(COLORS)], width=1.5),
            fill='tozeroy' if sym == ticker else None,
            fillcolor='rgba(255,23,68,0.06)' if sym == ticker else None,
        ))
    fig_dd.update_layout(
        title='Drawdown from Peak (%)',
        paper_bgcolor=T['bg'], plot_bgcolor=T['panel'],
        font=dict(color=T['white'], family='monospace'),
        height=300, hovermode='x unified',
        xaxis=dict(gridcolor=T['border']),
        yaxis=dict(gridcolor=T['border'], title='Drawdown (%)'),
        legend=dict(orientation='h', y=1.08),
        margin=dict(l=10, r=10, t=50, b=10),
    )
    st.plotly_chart(fig_dd, use_container_width=True)

    st.caption(f"Usage: `TRA AAPL`  |  `TRA TSLA SPY QQQ`  |  `TRA MSFT 5y`")


def _max_drawdown(prices: pd.Series) -> float:
    peak = prices.cummax()
    dd   = (prices - peak) / peak
    return float(dd.min())


# ══════════════════════════════════════════════════════════════════════════════
# 13. RISK DASHBOARD  (RISK)
# ══════════════════════════════════════════════════════════════════════════════

def cmd_risk(parts: list):
    """
    RISK AAPL     – full risk dashboard vs SPY
    RISK AAPL QQQ – custom benchmark
    """
    if len(parts) < 2:
        st.error("Usage: RISK TICKER [benchmark]"); return

    import math
    from scipy import stats as scipy_stats

    ticker    = parts[1].upper()
    benchmark = parts[2].upper() if len(parts) > 2 else 'SPY'

    st.markdown(f"<div class='term-header'>⚠️  RISK DASHBOARD: {ticker} vs {benchmark}</div>",
                unsafe_allow_html=True)

    with st.spinner("Computing risk metrics…"):
        df_t = yf.Ticker(ticker).history(   period='3y', interval='1d', auto_adjust=True)
        df_b = yf.Ticker(benchmark).history(period='3y', interval='1d', auto_adjust=True)

    if df_t.empty:
        st.error(f"No data for {ticker}"); return

    rt = df_t['Close'].pct_change().dropna()
    rb = df_b['Close'].pct_change().dropna() if not df_b.empty else None

    # Align
    if rb is not None:
        common = rt.index.intersection(rb.index)
        rt_a   = rt.loc[common]
        rb_a   = rb.loc[common]
    else:
        rt_a = rt; rb_a = None

    ann = math.sqrt(252)

    # Core metrics
    ann_ret  = (df_t['Close'].iloc[-1] / df_t['Close'].iloc[0]) ** (252/max(len(df_t),1)) - 1
    ann_vol  = rt.std() * ann
    sharpe   = ann_ret / ann_vol if ann_vol > 0 else 0
    mdd      = _max_drawdown(df_t['Close'])
    var95    = float(np.percentile(rt, 5)  * 100)
    var99    = float(np.percentile(rt, 1)  * 100)
    tail95   = rt[rt <= np.percentile(rt, 5)]
    cvar95   = float(tail95.mean() * 100) if len(tail95) else 0
    skew     = float(scipy_stats.skew(rt))
    kurt     = float(scipy_stats.kurtosis(rt))

    # Beta, alpha, correlation vs benchmark
    beta = alpha = corr = None
    if rb_a is not None and len(rb_a) > 30:
        slope, intercept, r_val, _, _ = scipy_stats.linregress(rb_a, rt_a)
        beta  = slope
        alpha = (intercept * 252) * 100   # annualised alpha %
        corr  = r_val ** 2                 # R²

    # ── KPI strip ─────────────────────────────────────────────────────────
    m = st.columns(8)
    m[0].metric("Ann. Return",  f"{ann_ret*100:+.1f}%")
    m[1].metric("Ann. Vol",     f"{ann_vol*100:.1f}%")
    m[2].metric("Sharpe",       f"{sharpe:.2f}")
    m[3].metric("Max DD",       f"{mdd*100:.1f}%")
    m[4].metric("VaR 95%",      f"{var95:.2f}%")
    m[5].metric("CVaR 95%",     f"{cvar95:.2f}%")
    m[6].metric("Beta",         f"{beta:.2f}" if beta is not None else "—",
                help=f"vs {benchmark}")
    m[7].metric("Alpha (ann.)", f"{alpha:+.1f}%" if alpha is not None else "—")

    st.markdown("---")
    c1, c2 = st.columns(2)
    with c1:
        st.metric("VaR 99%",      f"{var99:.2f}%")
        st.metric("Skewness",     f"{skew:.3f}")
        st.metric("Excess Kurt",  f"{kurt:.3f}")
        if corr is not None:
            st.metric(f"R² vs {benchmark}", f"{corr:.3f}")

    with c2:
        # Volatility regime: 30d vs 252d
        rv30  = rt.tail(21).std()  * ann * 100
        rv252 = rt.std()           * ann * 100
        st.metric("30D RV",   f"{rv30:.1f}%")
        st.metric("1Y RV",    f"{rv252:.1f}%")
        st.metric("RV Ratio", f"{rv30/rv252:.2f}x" if rv252 > 0 else "—",
                  help=">1 = vol expanding, <1 = vol contracting")

    # ── Scatter: ticker vs benchmark daily returns ─────────────────────────
    if rb_a is not None:
        fig_sc = go.Figure()
        fig_sc.add_trace(go.Scatter(
            x=rb_a * 100, y=rt_a * 100,
            mode='markers',
            marker=dict(size=4, color=T['amber'], opacity=0.5),
            name='Daily Returns',
            hovertemplate=f"{benchmark}: %{{x:.2f}}%<br>{ticker}: %{{y:.2f}}%<extra></extra>",
        ))
        # Regression line
        x_line = np.linspace(float(rb_a.min()*100), float(rb_a.max()*100), 100)
        y_line = beta * x_line/100 * 100 + intercept * 100
        fig_sc.add_trace(go.Scatter(
            x=x_line, y=y_line,
            mode='lines',
            line=dict(color=T['red'], width=2, dash='dot'),
            name=f'β={beta:.2f}',
        ))
        fig_sc.add_hline(y=0, line_color=T['muted'], opacity=0.4)
        fig_sc.add_vline(x=0, line_color=T['muted'], opacity=0.4)
        fig_sc.update_layout(
            title=f'{ticker} vs {benchmark} — Daily Returns Scatter (3Y)',
            paper_bgcolor=T['bg'], plot_bgcolor=T['panel'],
            font=dict(color=T['white'], family='monospace'),
            height=380,
            xaxis=dict(gridcolor=T['border'], title=f'{benchmark} Daily Return (%)'),
            yaxis=dict(gridcolor=T['border'], title=f'{ticker} Daily Return (%)'),
            legend=dict(orientation='h'),
            margin=dict(l=10, r=10, t=50, b=10),
        )
        st.plotly_chart(fig_sc, use_container_width=True)

    # ── Rolling beta chart ─────────────────────────────────────────────────
    if rb_a is not None and len(rb_a) >= 126:
        roll_beta = rt_a.rolling(126).cov(rb_a) / rb_a.rolling(126).var()
        fig_rb = go.Figure(go.Scatter(
            x=roll_beta.index, y=roll_beta,
            line=dict(color=T['amber'], width=2),
            name='6M Rolling Beta',
        ))
        fig_rb.add_hline(y=1,    line_dash='dot', line_color=T['muted'], opacity=0.5,
                         annotation_text='β=1', annotation_font=dict(color=T['muted']))
        fig_rb.add_hline(y=beta, line_dash='dot', line_color=T['blue'],  opacity=0.6,
                         annotation_text=f'Avg β={beta:.2f}',
                         annotation_font=dict(color=T['blue']))
        fig_rb.update_layout(
            title=f'{ticker} Rolling 6M Beta vs {benchmark}',
            paper_bgcolor=T['bg'], plot_bgcolor=T['panel'],
            font=dict(color=T['white'], family='monospace'),
            height=300, hovermode='x unified',
            xaxis=dict(gridcolor=T['border']),
            yaxis=dict(gridcolor=T['border'], title='Beta'),
            margin=dict(l=10, r=10, t=50, b=10),
        )
        st.plotly_chart(fig_rb, use_container_width=True)

    st.caption(f"Usage: `RISK AAPL`  |  `RISK TSLA QQQ`  |  `RISK NVDA SPY`")


# ══════════════════════════════════════════════════════════════════════════════
# 14. TOP NEWS  (TOP)
# ══════════════════════════════════════════════════════════════════════════════

def cmd_top(api_keys: dict):
    """TOP — today's top market news merged from FMP + Alpha Vantage + yfinance."""
    import requests as _req
    from datetime import datetime, timezone

    st.markdown("<div class='term-header'>📰  TOP — TODAY'S TOP MARKET NEWS</div>",
                unsafe_allow_html=True)

    now_utc  = datetime.now(timezone.utc)
    av_key   = api_keys.get('alpha_vantage', '')
    fmp_key  = api_keys.get('fmp', '')

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _time_ago(seconds: int) -> str:
        if seconds < 3600:  return f"{seconds // 60}m ago"
        if seconds < 86400: return f"{seconds // 3600}h ago"
        return f"{seconds // 86400}d ago"

    def _sentiment_badge(score) -> str:
        if score is None: return ''
        s = float(score)
        if s >= 0.35:  return f"<span style='color:{T['green']};font-size:10px'>▲ BULLISH &nbsp;</span>"
        if s <= -0.35: return f"<span style='color:{T['red']};font-size:10px'>▼ BEARISH &nbsp;</span>"
        return f"<span style='color:{T['amber']};font-size:10px'>● NEUTRAL &nbsp;</span>"

    def _src_label(src: str) -> str:
        colors = {'AV': T['blue'], 'FMP': T['green'], 'YF': T['muted']}
        labels = {'AV': 'Alpha Vantage', 'FMP': 'FMP', 'YF': 'yfinance'}
        c = colors.get(src, T['muted'])
        l = labels.get(src, src)
        return (f"<span style='color:{c};font-family:monospace;font-size:9px;"
                f"border:1px solid {c};padding:0 4px;border-radius:2px'>{l}</span>")

    def _pills(tickers: list) -> str:
        return '  '.join(
            f"<span style='background:{T['header']};color:{T['amber']};"
            f"font-family:monospace;font-size:10px;padding:1px 5px;"
            f"border-radius:3px'>{tk}</span>"
            for tk in tickers[:5] if tk
        )

    # Unified article schema:
    # {title, url, source, publisher, ago_sec, summary, tickers, sentiment, category, _src}
    all_articles: list[dict] = []
    seen: set[str] = set()

    def _dedup_add(art: dict):
        key = art['title'].strip().lower()[:80]
        if key not in seen:
            seen.add(key)
            all_articles.append(art)

    # ── Source 1: FMP — /v3/stock_news (no key needed for limited, key for more) ──
    fmp_articles = []
    try:
        params = {'limit': 50}
        if fmp_key:
            params['apikey'] = fmp_key
        else:
            params['apikey'] = 'demo'
        r = _req.get('https://financialmodelingprep.com/api/v3/stock_news',
                     params=params, timeout=10)
        if r.status_code == 200:
            fmp_articles = r.json() if isinstance(r.json(), list) else []
    except:
        pass

    for art in fmp_articles:
        try:
            pub = art.get('publishedDate', '')
            dt  = datetime.fromisoformat(pub.replace('Z', '+00:00')) if pub else now_utc
            sec = int((now_utc - dt.replace(tzinfo=timezone.utc)
                       if dt.tzinfo is None else now_utc - dt).total_seconds())
            cat = 'MARKETS'
            sym = art.get('symbol', '')
            _dedup_add({
                'title':     art.get('title', '—'),
                'url':       art.get('url', '#'),
                'publisher': art.get('site', '—'),
                'ago_sec':   max(sec, 0),
                'summary':   art.get('text', '')[:220],
                'tickers':   [sym] if sym else [],
                'sentiment': None,
                'category':  cat,
                '_src':      'FMP',
            })
        except:
            pass

    # ── Source 2: FMP — /v4/general_news (broader, non-stock) ────────────────
    try:
        params2 = {'limit': 30}
        if fmp_key:
            params2['apikey'] = fmp_key
        else:
            params2['apikey'] = 'demo'
        r2 = _req.get('https://financialmodelingprep.com/api/v4/general_news',
                      params=params2, timeout=10)
        if r2.status_code == 200:
            for art in (r2.json() if isinstance(r2.json(), list) else []):
                try:
                    pub = art.get('publishedDate', '')
                    dt  = datetime.fromisoformat(pub.replace('Z', '+00:00')) if pub else now_utc
                    sec = int((now_utc - dt.replace(tzinfo=timezone.utc)
                               if dt.tzinfo is None else now_utc - dt).total_seconds())
                    _dedup_add({
                        'title':     art.get('title', '—'),
                        'url':       art.get('url', '#'),
                        'publisher': art.get('site', '—'),
                        'ago_sec':   max(sec, 0),
                        'summary':   art.get('text', '')[:220],
                        'tickers':   [],
                        'sentiment': None,
                        'category':  'MACRO',
                        '_src':      'FMP',
                    })
                except:
                    pass
    except:
        pass

    # ── Source 3: Alpha Vantage — NEWS_SENTIMENT (best sentiment data) ────────
    if av_key:
        try:
            r3 = _req.get(
                'https://www.alphavantage.co/query',
                params={
                    'function': 'NEWS_SENTIMENT',
                    'topics':   'financial_markets,earnings,economy_macro,ipo,mergers_and_acquisitions',
                    'sort':     'LATEST',
                    'limit':    50,
                    'apikey':   av_key,
                },
                timeout=12,
            )
            if r3.status_code == 200:
                av_cat_map = {
                    'earnings':                 'EARNINGS',
                    'ipo':                      'IPO / M&A',
                    'mergers_and_acquisitions': 'IPO / M&A',
                    'economy_macro':            'MACRO',
                    'economy_fiscal':           'MACRO',
                    'economy_monetary':         'MACRO',
                    'blockchain':               'CRYPTO',
                    'cryptocurrency':           'CRYPTO',
                    'technology':               'TECH',
                    'financial_markets':        'MARKETS',
                }
                for art in r3.json().get('feed', []):
                    try:
                        ts  = art.get('time_published', '')
                        dt  = datetime.strptime(ts, '%Y%m%dT%H%M%S').replace(tzinfo=timezone.utc)
                        sec = int((now_utc - dt).total_seconds())
                        topics = [t.get('topic', '') for t in art.get('topics', [])]
                        cat = next((av_cat_map[tp] for tp in topics if tp in av_cat_map), 'MARKETS')
                        tickers = [tk.get('ticker', '') for tk in art.get('ticker_sentiment', [])[:5]]
                        _dedup_add({
                            'title':     art.get('title', '—'),
                            'url':       art.get('url', '#'),
                            'publisher': art.get('source', '—'),
                            'ago_sec':   max(sec, 0),
                            'summary':   art.get('summary', '')[:220],
                            'tickers':   [t for t in tickers if t],
                            'sentiment': art.get('overall_sentiment_score'),
                            'category':  cat,
                            '_src':      'AV',
                        })
                    except:
                        pass
        except:
            pass

    # ── Source 4: yfinance — always-on fallback ───────────────────────────────
    yf_syms = ['^GSPC', '^DJI', '^VIX', 'SPY', 'QQQ', 'GLD', 'TLT', 'BTC-USD',
               'AAPL', 'MSFT', 'NVDA', 'TSLA', 'AMZN', 'META']
    for sym in yf_syms:
        try:
            for item in (yf.Ticker(sym).news or []):
                try:
                    ts  = item.get('providerPublishTime', 0)
                    sec = int((now_utc - datetime.fromtimestamp(int(ts), tz=timezone.utc)
                               ).total_seconds())
                    tickers = item.get('relatedTickers', [])[:4]
                    _dedup_add({
                        'title':     item.get('title', '—'),
                        'url':       item.get('link', '#'),
                        'publisher': item.get('publisher', '—'),
                        'ago_sec':   max(sec, 0),
                        'summary':   '',
                        'tickers':   tickers,
                        'sentiment': None,
                        'category':  'MARKETS',
                        '_src':      'YF',
                    })
                except:
                    pass
        except:
            pass

    # ── Sort merged feed by recency ───────────────────────────────────────────
    all_articles.sort(key=lambda x: x['ago_sec'])

    if not all_articles:
        st.error("Could not load news from any source. Check your connection or API keys.")
        return

    # Source summary chips
    src_counts = {}
    for a in all_articles:
        src_counts[a['_src']] = src_counts.get(a['_src'], 0) + 1
    _src_colors = {'AV': T['blue'], 'FMP': T['green'], 'YF': T['muted']}
    _src_names  = {'AV': 'Alpha Vantage', 'FMP': 'FMP', 'YF': 'yfinance'}
    chips = '  '.join(
        "<span style='color:{};font-family:monospace;font-size:11px'>{} from {}</span>".format(
            _src_colors.get(s, T['muted']), n, _src_names.get(s, s))
        for s, n in sorted(src_counts.items(), key=lambda x: -x[1])
    )
    st.markdown(f"<div style='margin-bottom:8px'>{chips} &nbsp;|&nbsp; "
                f"<span style='color:{T['muted']};font-family:monospace;font-size:11px'>"
                f"{len(all_articles)} articles total</span></div>",
                unsafe_allow_html=True)

    # ── Category tabs ─────────────────────────────────────────────────────────
    categories = ['ALL', 'EARNINGS', 'MACRO', 'IPO / M&A', 'MARKETS', 'CRYPTO', 'TECH']
    tab_objs   = st.tabs(categories)

    def _render_article(art: dict):
        badge   = _sentiment_badge(art['sentiment'])
        pill_ht = _pills(art['tickers'])
        src_ht  = _src_label(art['_src'])
        ago_str = _time_ago(art['ago_sec'])
        summary = art.get('summary', '')
        st.markdown(
            f"<div class='term-panel' style='padding:10px 14px;margin-bottom:6px'>"
            f"<div style='display:flex;justify-content:space-between;align-items:baseline'>"
            f"<span style='color:{T['amber']};font-family:monospace;font-weight:bold;font-size:12px'>"
            f"{badge}"
            f"<a href='{art['url']}' target='_blank' "
            f"style='color:{T['amber']};text-decoration:none'>{art['title']}</a>"
            f"</span>"
            f"<span style='color:{T['muted']};font-family:monospace;font-size:10px;"
            f"white-space:nowrap;margin-left:12px'>{ago_str}</span>"
            f"</div>"
            + (f"<div style='color:{T['muted']};font-family:monospace;"
               f"font-size:10px;margin-top:4px'>{summary}…</div>" if summary else "")
            + (f"<div style='margin-top:5px'>{pill_ht}</div>" if pill_ht else "")
            + f"<div style='color:{T['muted']};font-family:monospace;font-size:10px;"
              f"margin-top:4px'>{src_ht} &nbsp; 📡 {art['publisher']}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

    for tab, cat in zip(tab_objs, categories):
        with tab:
            filtered = all_articles if cat == 'ALL' else [
                a for a in all_articles if a['category'] == cat
            ]
            if not filtered:
                st.info(f"No {cat} articles right now.")
                continue
            for art in filtered[:20]:
                _render_article(art)

    # ── Sentiment chart (AV articles only) ────────────────────────────────────
    av_only = [a for a in all_articles if a['_src'] == 'AV' and a['sentiment'] is not None]
    if av_only:
        st.markdown("---")
        st.markdown("**📊 Sentiment Distribution (Alpha Vantage articles)**")
        bull = sum(1 for a in av_only if float(a['sentiment']) >= 0.35)
        neut = sum(1 for a in av_only if -0.35 < float(a['sentiment']) < 0.35)
        bear = sum(1 for a in av_only if float(a['sentiment']) <= -0.35)
        fig_s = go.Figure(go.Bar(
            x=['Bullish', 'Neutral', 'Bearish'],
            y=[bull, neut, bear],
            marker_color=[T['green'], T['amber'], T['red']],
            text=[bull, neut, bear], textposition='outside',
            textfont=dict(color=T['white'], family='monospace'),
        ))
        fig_s.update_layout(
            paper_bgcolor=T['bg'], plot_bgcolor=T['panel'],
            font=dict(color=T['white'], family='monospace'),
            height=240, xaxis=dict(gridcolor=T['border']),
            yaxis=dict(gridcolor=T['border'], title='# Articles'),
            margin=dict(l=10, r=10, t=20, b=10),
        )
        st.plotly_chart(fig_s, use_container_width=True)

    keys_missing = [k for k, v in [('Alpha Vantage', av_key), ('FMP', fmp_key)] if not v]
    if keys_missing:
        st.caption(f"💡 Add {' + '.join(keys_missing)} API key(s) in Terminal → API Keys for more articles & sentiment.")
    st.caption("Usage: `TOP`")

# ══════════════════════════════════════════════════════════════════════════════
# POLYGON IV — Implied Volatility Dashboard  (IV TICKER [period])
# Uses Polygon.io REST API for live options snapshots + Black-Scholes pricing
# ══════════════════════════════════════════════════════════════════════════════

import math as _math

# ─── Black-Scholes engine ──────────────────────────────────────────────────────

def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + _math.erf(x / _math.sqrt(2.0)))

def _bs_price(S: float, K: float, T_yr: float, r: float, sigma: float,
              flag: str = 'call') -> float | None:
    """European Black-Scholes price for call or put."""
    if T_yr <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return None
    try:
        sq  = sigma * _math.sqrt(T_yr)
        d1  = (_math.log(S / K) + (r + 0.5 * sigma**2) * T_yr) / sq
        d2  = d1 - sq
        disc = _math.exp(-r * T_yr)
        if flag == 'call':
            return S * _norm_cdf(d1) - K * disc * _norm_cdf(d2)
        else:
            return K * disc * _norm_cdf(-d2) - S * _norm_cdf(-d1)
    except Exception:
        return None

def _bs_greeks(S: float, K: float, T_yr: float, r: float, sigma: float,
               flag: str = 'call') -> dict:
    """ATM Greeks dict: delta, gamma, theta ($/day), vega (per 1% IV), rho."""
    if T_yr <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return {}
    try:
        sq   = sigma * _math.sqrt(T_yr)
        d1   = (_math.log(S / K) + (r + 0.5 * sigma**2) * T_yr) / sq
        d2   = d1 - sq
        disc = _math.exp(-r * T_yr)
        npd1 = _math.exp(-0.5 * d1**2) / _math.sqrt(2 * _math.pi)
        nd1  = _norm_cdf(d1);  nd2  = _norm_cdf(d2)
        nd1n = _norm_cdf(-d1); nd2n = _norm_cdf(-d2)
        gamma = npd1 / (S * sq)
        vega  = S * npd1 * _math.sqrt(T_yr) / 100
        if flag == 'call':
            delta = nd1
            theta = (-(S * npd1 * sigma) / (2 * _math.sqrt(T_yr))
                     - r * K * disc * nd2) / 365
            rho   =  K * T_yr * disc * nd2  / 100
        else:
            delta = nd1 - 1
            theta = (-(S * npd1 * sigma) / (2 * _math.sqrt(T_yr))
                     + r * K * disc * nd2n) / 365
            rho   = -K * T_yr * disc * nd2n / 100
        return {'delta': delta, 'gamma': gamma, 'theta': theta,
                'vega': vega, 'rho': rho}
    except Exception:
        return {}

# ─── Polygon helpers ───────────────────────────────────────────────────────────

_POLY = "https://api.polygon.io"

def _poly(endpoint: str, key: str, params: dict | None = None) -> dict:
    try:
        p = dict(params or {}); p['apiKey'] = key
        r = requests.get(f"{_POLY}{endpoint}", params=p, timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {}

def _poly_spot(ticker: str, key: str) -> float | None:
    """Latest price from Polygon snapshot."""
    d = _poly(f"/v2/snapshot/locale/us/markets/stocks/tickers/{ticker}", key)
    t = d.get('ticker', {})
    return (t.get('day', {}).get('c') or t.get('prevDay', {}).get('c') or None)

def _poly_aggs(ticker: str, key: str, from_d: str, to_d: str) -> pd.DataFrame:
    """Daily OHLCV from Polygon aggs."""
    d = _poly(f"/v2/aggs/ticker/{ticker}/range/1/day/{from_d}/{to_d}", key,
              {'adjusted': 'true', 'sort': 'asc', 'limit': 5000})
    res = d.get('results', [])
    if not res:
        return pd.DataFrame()
    df = pd.DataFrame(res)
    df['date'] = pd.to_datetime(df['t'], unit='ms', utc=True).dt.tz_convert(None)
    return df.rename(columns={'c': 'close', 'o': 'open', 'h': 'high',
                               'l': 'low', 'v': 'volume'}).set_index('date').sort_index()

def _poly_options_snapshot(ticker: str, key: str,
                            contract_type: str = 'call') -> list:
    """Fetch near-term options snapshot from Polygon."""
    today  = date.today()
    exp_to = (today + timedelta(days=120)).isoformat()
    d = _poly(f"/v3/snapshot/options/{ticker}", key, {
        'contract_type':  contract_type,
        'expiration_date.gte': today.isoformat(),
        'expiration_date.lte': exp_to,
        'order': 'asc', 'sort': 'expiration_date', 'limit': 250,
    })
    return d.get('results', [])

def _poly_iv_term(ticker: str, key: str) -> dict:
    """
    Build IV term structure (1D / 9D / 1M / 3M) from Polygon options snapshot.
    Returns {label: {iv, dte, strike, expiry, delta_dist}}.
    """
    results = _poly_options_snapshot(ticker, key, 'call')
    if not results:
        return {}

    today   = date.today()
    targets = {'1D': 1, '9D': 9, '1M': 30, '3M': 91}
    best: dict = {}

    for c in results:
        det = c.get('details', {})
        exp = det.get('expiration_date', '')
        iv_raw = c.get('implied_volatility')
        if not exp or not iv_raw or float(iv_raw) <= 0:
            continue
        try:
            dte = (date.fromisoformat(exp) - today).days
        except Exception:
            continue
        if dte < 0 or dte > 100:
            continue

        delta_abs = abs((c.get('greeks') or {}).get('delta', 0.5))
        iv_pct    = float(iv_raw) * 100

        for lbl, tgt in targets.items():
            dte_diff  = abs(dte - tgt)
            prev      = best.get(lbl)
            # Prefer closer DTE, then closer to delta 0.50
            if (prev is None
                    or dte_diff < prev['dte_diff']
                    or (dte_diff == prev['dte_diff']
                        and abs(delta_abs - 0.5) < prev['delta_dist'])):
                best[lbl] = {
                    'iv':         iv_pct,
                    'dte':        dte,
                    'dte_diff':   dte_diff,
                    'delta_dist': abs(delta_abs - 0.5),
                    'strike':     det.get('strike_price'),
                    'expiry':     exp,
                }
    return best

def _poly_iv_history(ticker: str, key: str, lookback: int = 365) -> pd.Series | None:
    """
    Historical ATM IV approximation using Polygon's options snapshot series.
    Polygon free tier doesn't expose point-in-time historical IV, so we use
    rolling 21-day realised vol of Polygon price data as a proxy when needed.
    Returns pd.Series of annualised IV% indexed by date (may be RV proxy).
    """
    to_d   = date.today().isoformat()
    from_d = (date.today() - timedelta(days=lookback)).isoformat()
    df     = _poly_aggs(ticker, key, from_d, to_d)
    if df.empty or 'close' not in df.columns:
        return None
    rets = df['close'].pct_change().dropna()
    # 21-day rolling realised vol as historical IV proxy
    rv = rets.rolling(21).std() * _math.sqrt(252) * 100
    return rv.dropna()

def _risk_free() -> float:
    """3-month T-bill rate from yfinance ^IRX, fallback 4.5%."""
    try:
        import yfinance as yf
        fi = yf.Ticker('^IRX').fast_info
        v  = getattr(fi, 'last_price', None) or getattr(fi, 'previous_close', None)
        if v and float(v) > 0:
            return float(v) / 100
    except Exception:
        pass
    return 0.045

# ─── Main command ──────────────────────────────────────────────────────────────

def cmd_polygon_iv(parts: list, api_keys: dict):
    """
    IV TICKER [period]
    Full implied-volatility dashboard powered by Polygon.io:
      • Live IV term structure  1D / 9D / 1M / 3M  (ATM calls)
      • Historical realised vol vs current IV — IV premium / discount
      • ATM + ±2.5% / ±5% option prices (BS) using current IV and historical RV
      • IV vs Historical-price comparison at each tenor tab
      • Greeks strip (Δ call, Δ put, Γ, Θ, ν)
      • IV skew chart for nearest 30-DTE expiry
      • IV Rank and IV Percentile vs 1-year realised vol range
    """
    from scipy import stats as scipy_stats

    if len(parts) < 2:
        st.error("Usage:  IV TICKER [period]   e.g.  IV AAPL   IV TSLA 1y")
        return

    poly_key = api_keys.get('polygon', '').strip()
    if not poly_key:
        st.warning("⚠️ **Polygon.io API key required.**")
        st.markdown(
            "Add it under **🔑 API Keys → Polygon.io** in the terminal, then run the command again.  \n"
            "Get a free key at [polygon.io](https://polygon.io) — the Starter plan covers "
            "options snapshots and historical prices.")
        return

    valid_periods = {'3mo': 95, '6mo': 185, '1y': 370, '2y': 740}
    ticker = None
    period = '1y'
    for p in parts[1:]:
        if p.lower() in valid_periods:
            period = p.lower()
        else:
            ticker = p.upper()
    if not ticker:
        st.error("Usage:  IV TICKER  e.g.  IV AAPL"); return

    lookback = valid_periods[period]

    st.markdown(
        f"<div class='term-header'>🌡️  IV DASHBOARD — {ticker}  [{period.upper()}]</div>",
        unsafe_allow_html=True)

    # ── Fetch everything ──────────────────────────────────────────────────────
    with st.spinner(f"Loading {ticker} from Polygon.io…"):
        rf       = _risk_free()
        spot     = _poly_spot(ticker, poly_key)
        iv_term  = _poly_iv_term(ticker, poly_key)
        hist_rv  = _poly_iv_history(ticker, poly_key, lookback)

        # Fallback spot from yfinance
        if not spot:
            try:
                import yfinance as yf
                fi   = yf.Ticker(ticker).fast_info
                spot = getattr(fi, 'last_price', None) or getattr(fi, 'previous_close', None)
                if spot: spot = float(spot)
            except Exception:
                pass

    if not spot:
        st.error(f"Cannot get spot price for **{ticker}**. Check the ticker and your Polygon key.")
        return

    # ── RV metric lookup ──────────────────────────────────────────────────────
    rv_metrics: dict[str, float] = {}
    if hist_rv is not None and len(hist_rv) >= 10:
        ann = _math.sqrt(252)
        # hist_rv is already annualised %
        for lbl, w in [('10D', 10), ('21D', 21), ('63D', 63)]:
            if len(hist_rv) >= w:
                rv_metrics[lbl] = float(hist_rv.tail(w).mean())
        rv_metrics['1Y'] = float(hist_rv.mean())

    # ── Header info bar ───────────────────────────────────────────────────────
    st.markdown(
        f"<div style='font-family:monospace;font-size:12px;color:{T['muted']};margin-bottom:8px'>"
        f"Spot: <b style='color:{T['amber']}'>${spot:,.2f}</b>"
        f"  ·  Risk-free: <b>{rf*100:.2f}%</b>"
        f"  ·  Source: <b style='color:{T['green']}'>Polygon.io</b></div>",
        unsafe_allow_html=True)

    # ═════════════════════════════════════════════════════════════════════════
    # SECTION 1 — IV Term Structure strip
    # ═════════════════════════════════════════════════════════════════════════
    st.markdown("<div class='term-header' style='font-size:12px'>📐 IV TERM STRUCTURE (ATM CALLS)</div>",
                unsafe_allow_html=True)

    dte_labels = ['1D', '9D', '1M', '3M']
    n_rv       = len(rv_metrics)
    iv_cols    = st.columns(len(dte_labels) + n_rv)
    iv_values: dict[str, float] = {}

    rv_for_tenor = {'1D': '10D', '9D': '10D', '1M': '21D', '3M': '63D'}
    for i, lbl in enumerate(dte_labels):
        info = iv_term.get(lbl)
        if info:
            iv_val = info['iv']
            iv_values[lbl] = iv_val
            rv_lbl = rv_for_tenor[lbl]
            rv_val = rv_metrics.get(rv_lbl)
            delta_str = f"vs {rv_lbl} RV {iv_val - rv_val:+.1f}%" if rv_val else None
            iv_cols[i].metric(f"{lbl} IV", f"{iv_val:.1f}%", delta=delta_str,
                              delta_color="inverse",
                              help=f"Expiry: {info['expiry']}  Strike: {info['strike']}")
        else:
            iv_cols[i].metric(f"{lbl} IV", "—",
                              help="No Polygon data for this tenor")

    for j, (rv_lbl, rv_val) in enumerate(rv_metrics.items()):
        iv_cols[len(dte_labels) + j].metric(f"{rv_lbl} RV", f"{rv_val:.1f}%",
                                             help="21-day rolling realised vol (annualised)")

    if not iv_values:
        st.warning(
            "Polygon returned no options data for this ticker.  "
            "This may mean:\n"
            "- The ticker has no listed options\n"
            "- Your Polygon plan doesn't include options snapshots\n"
            "- The market is closed and no snapshot is cached\n\n"
            "The realised vol and historical price sections below still work.")

    # ═════════════════════════════════════════════════════════════════════════
    # SECTION 2 — Realised Vol vs Implied Vol chart
    # ═════════════════════════════════════════════════════════════════════════
    if hist_rv is not None and len(hist_rv) >= 21:
        st.markdown("---")
        st.markdown(
            f"<div class='term-header' style='font-size:12px'>"
            f"📈 REALISED VOL vs IMPLIED VOL — {period.upper()}</div>",
            unsafe_allow_html=True)

        fig_rv = go.Figure()
        fig_rv.add_trace(go.Scatter(
            x=hist_rv.index, y=hist_rv.values,
            name='21D RV (rolling)', fill='tozeroy',
            fillcolor=f"rgba(21,101,192,0.08)",
            line=dict(color=T['blue'], width=1.8)))

        if len(hist_rv) >= 63:
            rv63 = hist_rv.rolling(63).mean()
            fig_rv.add_trace(go.Scatter(
                x=rv63.index, y=rv63.values,
                name='63D RV (rolling)',
                line=dict(color=T['green'], width=1.4, dash='dot')))

        line_cols = {'1D': '#ef5350', '9D': T['amber'], '1M': '#ce93d8', '3M': '#80cbc4'}
        for lbl, iv_val in iv_values.items():
            fig_rv.add_hline(
                y=iv_val,
                line=dict(color=line_cols.get(lbl, T['red']), dash='dash', width=1.5),
                annotation_text=f"{lbl} IV {iv_val:.1f}%",
                annotation_font=dict(color=line_cols.get(lbl, T['red']),
                                     size=9, family='monospace'),
                annotation_position='right')

        fig_rv.update_layout(
            title=f'{ticker}  —  Realised Vol vs Current Implied Vol ({period.upper()})',
            paper_bgcolor=T['bg'], plot_bgcolor=T['panel'],
            font=dict(color=T['white'], family='monospace'),
            height=380, hovermode='x unified',
            xaxis=dict(gridcolor=T['border']),
            yaxis=dict(gridcolor=T['border'], title='Annualised Vol (%)'),
            legend=dict(orientation='h', y=1.08),
            margin=dict(l=10, r=10, t=50, b=10))
        st.plotly_chart(fig_rv, use_container_width=True)

        # IV Premium / IV Rank summary
        if iv_values and rv_metrics.get('21D'):
            iv_1m    = iv_values.get('1M') or iv_values.get('9D') or next(iter(iv_values.values()))
            rv21     = rv_metrics['21D']
            premium  = iv_1m - rv21
            regime   = ('Expensive' if premium > 3
                        else 'Cheap' if premium < -3 else 'Fair')
            pm1, pm2, pm3, pm4 = st.columns(4)
            pm1.metric("1M IV",       f"{iv_1m:.1f}%")
            pm2.metric("21D RV",      f"{rv21:.1f}%")
            pm3.metric("IV Premium",  f"{premium:+.1f}%", delta=regime, delta_color="off")

            # IV Rank vs trailing 1Y realised vol range
            if len(hist_rv) >= 60:
                lo, hi = float(hist_rv.min()), float(hist_rv.max())
                iv_rank = (iv_1m - lo) / (hi - lo) * 100 if hi > lo else 50.0
                iv_pct  = float(scipy_stats.percentileofscore(hist_rv.values, iv_1m))
                pm4.metric("IV Rank (1Y)", f"{iv_rank:.0f}%",
                           help=f"IV Percentile: {iv_pct:.0f}%  "
                                f"(0%=lowest RV in period, 100%=highest)")

    # ═════════════════════════════════════════════════════════════════════════
    # SECTION 3 — Option pricing table  (tabbed by tenor)
    # ═════════════════════════════════════════════════════════════════════════
    st.markdown("---")
    st.markdown(
        "<div class='term-header' style='font-size:12px'>"
        "💰 ATM OPTION PRICES — BLACK-SCHOLES  (Current IV  vs  Historical RV)</div>",
        unsafe_allow_html=True)

    tenors = [
        ('1D',  1,  '10D'),
        ('9D',  9,  '10D'),
        ('1M',  30, '21D'),
        ('3M',  91, '63D'),
    ]
    tabs = st.tabs([f"📅 {lbl}" for lbl, _, _ in tenors])
    moneyness_pct = [-5.0, -2.5, 0.0, 2.5, 5.0]
    strikes = [round(spot * (1 + m / 100), 2) for m in moneyness_pct]

    for tab, (tenor_lbl, dte, rv_lbl) in zip(tabs, tenors):
        with tab:
            T_yr    = dte / 365.0
            iv_info = iv_term.get(tenor_lbl)
            iv_curr = iv_info['iv'] / 100 if iv_info else None
            rv_val  = rv_metrics.get(rv_lbl)
            rv_frac = rv_val / 100 if rv_val else None
            expiry  = (date.today() + timedelta(days=dte)).strftime('%Y-%m-%d')

            # Metadata strip
            mc1, mc2, mc3 = st.columns(3)
            mc1.metric("DTE", str(dte), help=f"Target expiry ≈ {expiry}")
            mc2.metric("Current IV",
                       f"{iv_curr*100:.2f}%" if iv_curr else "N/A",
                       help=(f"From Polygon: expiry {iv_info['expiry']}, "
                             f"strike ${iv_info['strike']}")
                             if iv_info else "No Polygon options data")
            mc3.metric(f"Hist RV ({rv_lbl})",
                       f"{rv_val:.2f}%" if rv_val else "N/A",
                       help="Rolling realised vol used as historical vol estimate")

            if not iv_curr and not rv_frac:
                st.info("No vol data available for this tenor."); continue

            # Price table
            rows_p = []
            for K, mono in zip(strikes, moneyness_pct):
                row = {'Strike': f"${K:,.2f}", 'Mono %': f"{mono:+.1f}%"}

                if iv_curr:
                    cp = _bs_price(spot, K, T_yr, rf, iv_curr, 'call')
                    pp = _bs_price(spot, K, T_yr, rf, iv_curr, 'put')
                    row['Call (IV)'] = f"${cp:.4f}" if cp else '—'
                    row['Put  (IV)'] = f"${pp:.4f}" if pp else '—'
                else:
                    row['Call (IV)'] = '—'; row['Put  (IV)'] = '—'

                if rv_frac:
                    cr = _bs_price(spot, K, T_yr, rf, rv_frac, 'call')
                    pr = _bs_price(spot, K, T_yr, rf, rv_frac, 'put')
                    row['Call (RV)'] = f"${cr:.4f}" if cr else '—'
                    row['Put  (RV)'] = f"${pr:.4f}" if pr else '—'
                else:
                    row['Call (RV)'] = '—'; row['Put  (RV)'] = '—'

                # IV-vs-RV price diff for call (shows premium embedded in IV)
                if iv_curr and rv_frac:
                    cp_iv = _bs_price(spot, K, T_yr, rf, iv_curr, 'call')
                    cp_rv = _bs_price(spot, K, T_yr, rf, rv_frac, 'call')
                    if cp_iv is not None and cp_rv is not None:
                        row['Call Δ(IV-RV)'] = f"${cp_iv - cp_rv:+.4f}"
                    else:
                        row['Call Δ(IV-RV)'] = '—'
                else:
                    row['Call Δ(IV-RV)'] = ''

                rows_p.append(row)

            st.dataframe(pd.DataFrame(rows_p), use_container_width=True, hide_index=True)
            st.caption(
                "**Call (IV)** / **Put (IV)** = BS price using current implied vol from Polygon  |  "
                "**Call (RV)** / **Put (RV)** = BS price using historical realised vol  |  "
                "**Call Δ(IV-RV)** = extra premium embedded in current IV over history")

            # Greeks (ATM, current IV only)
            if iv_curr:
                K_atm  = min(strikes, key=lambda k: abs(k - spot))
                g_call = _bs_greeks(spot, K_atm, T_yr, rf, iv_curr, 'call')
                g_put  = _bs_greeks(spot, K_atm, T_yr, rf, iv_curr, 'put')
                if g_call:
                    st.markdown(
                        f"**ATM Greeks — Strike ${K_atm:,.2f} · {tenor_lbl} DTE · "
                        f"IV {iv_curr*100:.1f}%**")
                    gg1, gg2, gg3, gg4, gg5, gg6 = st.columns(6)
                    gg1.metric("Δ Call",    f"{g_call['delta']:+.4f}",
                               help="$/$ spot move")
                    gg2.metric("Δ Put",     f"{g_put['delta']:+.4f}")
                    gg3.metric("Γ",         f"{g_call['gamma']:.6f}",
                               help="Δ change per $1 spot")
                    gg4.metric("Θ $/day",   f"{g_call['theta']:+.4f}",
                               help="Time decay per calendar day")
                    gg5.metric("ν per 1%IV",f"{g_call['vega']:.4f}",
                               help="Price change per 1% IV move")
                    gg6.metric("ρ per 1%r", f"{g_call['rho']:.4f}",
                               help="Price change per 1% rate move")

    # ═════════════════════════════════════════════════════════════════════════
    # SECTION 4 — IV Skew chart
    # ═════════════════════════════════════════════════════════════════════════
    st.markdown("---")
    st.markdown(
        "<div class='term-header' style='font-size:12px'>📉 IV SKEW — NEAR-TERM SMILE</div>",
        unsafe_allow_html=True)

    with st.spinner("Fetching options chain for skew…"):
        all_calls = _poly_options_snapshot(ticker, poly_key, 'call')
        all_puts  = _poly_options_snapshot(ticker, poly_key, 'put')

    if all_calls and spot:
        today_d    = date.today()
        # Group into expiry buckets
        exp_groups: dict[str, list] = {}
        for chain, ctype in [(all_calls, 'call'), (all_puts, 'put')]:
            for c in chain:
                det = c.get('details', {})
                exp = det.get('expiration_date', '')
                iv_raw = c.get('implied_volatility')
                if not exp or not iv_raw or float(iv_raw) <= 0:
                    continue
                try:
                    dte_c = (date.fromisoformat(exp) - today_d).days
                except Exception:
                    continue
                if dte_c < 1 or dte_c > 60:
                    continue
                exp_groups.setdefault(exp, []).append({
                    'strike': det.get('strike_price', 0),
                    'iv':     float(iv_raw) * 100,
                    'dte':    dte_c,
                    'type':   ctype,
                })

        if exp_groups:
            # Pick expiry nearest 30 DTE
            best_exp  = min(exp_groups, key=lambda e: abs(exp_groups[e][0]['dte'] - 30))
            chain_dat = exp_groups[best_exp]
            dte_lbl   = chain_dat[0]['dte']

            def _skew_trace(chain_dat, ctype, color, name):
                pts = sorted(
                    [(d['strike'], d['iv']) for d in chain_dat
                     if d['type'] == ctype and 0 < d['iv'] < 300],
                    key=lambda x: x[0])
                sx = [(k - spot) / spot * 100 for k, _ in pts if abs((k-spot)/spot*100) <= 20]
                sy = [iv for k, iv in pts        if abs((k-spot)/spot*100) <= 20]
                if len(sx) < 3:
                    return None
                return go.Scatter(x=sx, y=sy, mode='lines+markers', name=name,
                                  line=dict(color=color, width=2),
                                  marker=dict(size=5, color=color))

            fig_sk = go.Figure()
            tr_c = _skew_trace(chain_dat, 'call', T['amber'], 'Calls')
            tr_p = _skew_trace(chain_dat, 'put',  T['blue'],  'Puts')
            if tr_c: fig_sk.add_trace(tr_c)
            if tr_p: fig_sk.add_trace(tr_p)

            if tr_c or tr_p:
                fig_sk.add_vline(x=0, line_dash='dot', line_color=T['muted'],
                                 opacity=0.5,
                                 annotation_text='ATM',
                                 annotation_font=dict(color=T['muted'],
                                                       size=9, family='monospace'))
                fig_sk.update_layout(
                    title=f'{ticker} IV Skew — Expiry {best_exp} ({dte_lbl} DTE)',
                    paper_bgcolor=T['bg'], plot_bgcolor=T['panel'],
                    font=dict(color=T['white'], family='monospace'),
                    height=340,
                    xaxis=dict(gridcolor=T['border'], title='Moneyness (%)'),
                    yaxis=dict(gridcolor=T['border'], title='Implied Vol (%)'),
                    legend=dict(orientation='h'),
                    margin=dict(l=10, r=10, t=45, b=10))
                st.plotly_chart(fig_sk, use_container_width=True)
                st.caption(
                    "Steep left tail on puts = market pricing in downside risk premium.  "
                    "Source: Polygon.io options snapshot.")
            else:
                st.info("Not enough near-ATM contracts returned for skew chart.")
        else:
            st.info("No options contracts in 1–60 DTE range found in Polygon snapshot.")
    else:
        st.info("No options snapshot data available from Polygon for this ticker.")

    st.caption(
        f"Usage: `IV AAPL`  |  `IV TSLA 1y`  |  `IV SPY`  "
        f"— Polygon.io API key required  ·  "
        f"[Get free key](https://polygon.io)")


# ── FRED fetch helper (local copy, no circular import) ─────────────────────

@st.cache_data(ttl=900, show_spinner=False)
def _fred_fetch(series_id: str, api_keys: dict = None, limit: int = 120) -> pd.DataFrame:
    fred_key = (api_keys or {}).get('fred', '')
    try:
        base = 'https://fred.stlouisfed.org/graph/fredgraph.csv'
        params = {'id': series_id}
        if fred_key: params['api_key'] = fred_key
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
    try:
        url = 'https://api.stlouisfed.org/fred/series/observations'
        params = {'series_id': series_id, 'file_type': 'json',
                  'observation_start': '2000-01-01', 'sort_order': 'desc', 'limit': limit}
        if fred_key: params['api_key'] = fred_key
        r = requests.get(url, params=params, timeout=10)
        if r.status_code == 200:
            obs = r.json().get('observations', [])
            df = pd.DataFrame(obs)[['date','value']].rename(columns={'date':'Date','value':'Value'})
            df['Date'] = pd.to_datetime(df['Date'])
            df['Value'] = pd.to_numeric(df['Value'], errors='coerce')
            df = df.dropna().sort_values('Date')
            return df
    except: pass
    return pd.DataFrame()


# ══════════════════════════════════════════════════════════════════════════════
# 16. IND — INDEX LOOKUP
# ══════════════════════════════════════════════════════════════════════════════

INDICES_MAP = [
    ('S&P 500',      '^GSPC'),    ('NASDAQ',       '^IXIC'),
    ('DOW',          '^DJI'),     ('Russell 2000', '^RUT'),
    ('FTSE 100',     '^FTSE'),    ('DAX',          '^GDAXI'),
    ('CAC 40',       '^FCHI'),    ('Nikkei 225',   '^N225'),
    ('Hang Seng',    '^HSI'),     ('Shanghai',     '000001.SS'),
    ('ASX 200',      '^AXJO'),    ('KOSPI',        '^KS11'),
    ('SENSEX',       '^BSESN'),   ('TSX',          '^GSPTSE'),
    ('SMI',          '^SSMI'),    ('IBEX 35',      '^IBEX'),
    ('VIX',          '^VIX'),     ('10Y Yield',    '^TNX'),
]

def cmd_ind(parts: list, api_keys: dict):
    """IND [ticker] — index lookup dashboard."""
    if len(parts) >= 2:
        ticker = parts[1].upper()
        _show_index_detail(ticker, api_keys)
        return

    st.markdown(f"<div class='term-header'>📊  IND — INDEX LOOKUP</div>",
                unsafe_allow_html=True)
    syms = [sym for _, sym in INDICES_MAP]
    rows = []
    try:
        data = yf.download(syms, period='2d', interval='1d', progress=False, auto_adjust=True)
        for name, sym in INDICES_MAP:
            try:
                closes = data['Close'][sym].dropna()
                if len(closes) >= 2:
                    prev, last = float(closes.iloc[-2]), float(closes.iloc[-1])
                    chg = last - prev
                    chg_p = chg / prev * 100
                    rows.append({'Index': name, 'Last': f"{last:,.2f}", 'Chg': chg, 'Chg%': chg_p})
            except: pass
    except: pass
    if not rows:
        for name, sym in INDICES_MAP:
            try:
                t = yf.Ticker(sym)
                df = t.history(period='5d', interval='1d', auto_adjust=True)
                if not df.empty and len(df) >= 2:
                    prev, last = float(df['Close'].iloc[-2]), float(df['Close'].iloc[-1])
                    chg = last - prev; chg_p = chg / prev * 100
                    rows.append({'Index': name, 'Last': f"{last:,.2f}", 'Chg': chg, 'Chg%': chg_p})
            except: pass
    if not rows:
        st.error("Could not fetch index data.")
        return

    c1, c2, c3, c4 = st.columns(4)
    for i, r in enumerate(rows):
        col = [c1, c2, c3, c4][i % 4]
        arrow = '▲' if r['Chg'] >= 0 else '▼'
        color = T['green'] if r['Chg'] >= 0 else T['red']
        col.markdown(
            f"<div class='term-panel' style='padding:8px;text-align:center'>"
            f"<div style='color:{T['amber']};font-family:monospace;font-weight:bold;font-size:11px'>{r['Index']}</div>"
            f"<div style='color:{T['white']};font-family:monospace;font-size:14px'>{r['Last']}</div>"
            f"<div style='color:{color};font-family:monospace;font-size:12px'>{arrow} {r['Chg%']:+.2f}%</div>"
            f"</div>", unsafe_allow_html=True)

    if rows:
        labels = [r['Index'] for r in rows]
        chg_pct = [r['Chg%'] for r in rows]
        bar_colors = [T['green'] if v >= 0 else T['red'] for v in chg_pct]
        fig = go.Figure(go.Bar(x=labels, y=chg_pct, marker_color=bar_colors,
                               text=[f"{v:+.2f}%" for v in chg_pct], textposition='outside'))
        fig.add_hline(y=0, line_color=T['muted'], opacity=0.5)
        fig.update_layout(title='Index Performance (%)', paper_bgcolor=T['bg'],
                          plot_bgcolor=T['panel'], font=dict(color=T['white'], family='monospace'),
                          height=380, xaxis_tickangle=-45, margin=dict(b=100))
        st.plotly_chart(fig, use_container_width=True)
    st.caption("Usage: `IND`  |  `IND SPX`  |  `IND ^GSPC`  —  For credit spreads, try `OAS`  |  `OAS IG`  |  `OASD`")


def _show_index_detail(ticker: str, api_keys: dict):
    """Show detailed view for a specific index."""
    st.markdown(f"<div class='term-header'>📊  IND — {ticker}</div>", unsafe_allow_html=True)
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
        df = t.history(period='1y', interval='1d', auto_adjust=True)
        if df.empty:
            st.error(f"No data for index: {ticker}")
            return

        last = float(df['Close'].iloc[-1])
        prev = float(df['Close'].iloc[-2]) if len(df) > 1 else last
        chg = last - prev
        chg_p = chg / prev * 100
        high_52w = float(df['Close'].max())
        low_52w = float(df['Close'].min())

        c1, c2, c3, c4 = st.columns(4)
        arrow = '▲' if chg >= 0 else '▼'
        clr = T['green'] if chg >= 0 else T['red']
        c1.metric("Last", f"{last:,.2f}", f"{arrow} {chg:+.2f} ({chg_p:+.2f}%)")
        c2.metric("Open", f"{float(df['Open'].iloc[-1]):,.2f}")
        c3.metric("52W High", f"{high_52w:,.2f}")
        c4.metric("52W Low", f"{low_52w:,.2f}")

        name = info.get('shortName') or info.get('longName') or ticker
        st.markdown(f"<div style='color:{T['muted']};font-family:monospace;font-size:12px;margin-bottom:8px'>{name}</div>",
                    unsafe_allow_html=True)

        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df.index, y=df['Close'], mode='lines',
                                 line=dict(color=T['amber'], width=2), name=ticker))
        fig.update_layout(title=f'{ticker} — 1 Year Price',
                          paper_bgcolor=T['bg'], plot_bgcolor=T['panel'],
                          font=dict(color=T['white'], family='monospace'), height=400)
        st.plotly_chart(fig, use_container_width=True)
    except Exception as e:
        st.error(f"Could not load index detail: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# 17. WB — WORLD BOND
# ══════════════════════════════════════════════════════════════════════════════

WORLD_BOND_MAP = [
    ('US',   'DGS10', 'DGS2',   'US'),
    ('UK',   'IRLTLT01GBM156N', 'IRLTLT01GBM156N', 'UK'),
    ('Germany', 'IRLTLT01DEA156N', 'IRLTLT01DEA156N', 'DE'),
    ('Japan',   'IRLTLT01JPM156N',  'IRLTLT01JPM156N',  'JP'),
    ('Canada',  'IRLTLT01CAA156N',  'IRLTLT01CAA156N',  'CA'),
    ('Australia','IRLTLT01AUM156N', 'IRLTLT01AUM156N',  'AU'),
    ('France',  'IRLTLT01FRM156N',  'IRLTLT01FRM156N',  'FR'),
    ('Italy',   'IRLTLT01ITM156N',  'IRLTLT01ITM156N',  'IT'),
]

def cmd_wb(parts: list, api_keys: dict):
    """WB — world bond yield dashboard."""
    st.markdown(f"<div class='term-header'>🌐  WB — WORLD BOND YIELDS</div>",
                unsafe_allow_html=True)
    rows = []
    for name, series_10y, series_2y, country in WORLD_BOND_MAP:
        try:
            df = _fred_fetch(series_10y, api_keys, limit=30)
            if df.empty:
                try:
                    t = yf.Ticker(f"^{country}10")
                    df2 = t.history(period='5d', interval='1d', auto_adjust=True)
                    if not df2.empty:
                        y = float(df2['Close'].iloc[-1])
                        py = float(df2['Close'].iloc[-2]) if len(df2) > 1 else y
                        chg = y - py
                        rows.append({'Country': name, '10Y': f"{y:.2f}%", 'Chg': chg, 'Yield': y})
                    else:
                        rows.append({'Country': name, '10Y': '—', 'Chg': 0, 'Yield': None})
                except:
                    rows.append({'Country': name, '10Y': '—', 'Chg': 0, 'Yield': None})
            else:
                y = float(df['Value'].iloc[-1])
                py = float(df['Value'].iloc[-2]) if len(df) > 1 else y
                chg = y - py
                rows.append({'Country': name, '10Y': f"{y:.2f}%", 'Chg': chg, 'Yield': y})
        except:
            rows.append({'Country': name, '10Y': '—', 'Chg': 0, 'Yield': None})

    c1, c2, c3, c4 = st.columns(4)
    for i, r in enumerate(rows):
        col = [c1, c2, c3, c4][i % 4]
        arrow = '▲' if r['Chg'] >= 0 else '▼'
        color = T['green'] if r['Chg'] >= 0 else T['red']
        col.markdown(
            f"<div class='term-panel' style='padding:8px;text-align:center'>"
            f"<div style='color:{T['amber']};font-family:monospace;font-weight:bold;font-size:11px'>{r['Country']}</div>"
            f"<div style='color:{T['white']};font-family:monospace;font-size:14px'>{r['10Y']}</div>"
            f"<div style='color:{color};font-family:monospace;font-size:12px'>{arrow} {r['Chg']:+.2f}bp</div>"
            f"</div>", unsafe_allow_html=True)

    vals = [r['Yield'] for r in rows if r['Yield'] is not None]
    if vals:
        labels = [r['Country'] for r in rows if r['Yield'] is not None]
        fig = go.Figure(go.Bar(x=labels, y=vals, marker_color=T['blue'],
                               text=[f"{v:.2f}%" for v in vals], textposition='outside'))
        fig.update_layout(title='10Y Government Bond Yields (%)',
                          paper_bgcolor=T['bg'], plot_bgcolor=T['panel'],
                          font=dict(color=T['white'], family='monospace'),
                          height=350, xaxis_tickangle=-30, margin=dict(b=60))
        st.plotly_chart(fig, use_container_width=True)

    # US yield curve from FRED
    try:
        fred_key = api_keys.get('fred', '')
        tenors = [('1M','TB1MS'),('3M','DGS3MO'),('6M','DGS6MO'),('1Y','DGS1'),
                  ('2Y','DGS2'),('3Y','DGS3'),('5Y','DGS5'),('7Y','DGS7'),
                  ('10Y','DGS10'),('20Y','DGS20'),('30Y','DGS30')]
        uc = []
        for lbl, sid in tenors:
            df = _fred_fetch(sid, api_keys, limit=5)
            if not df.empty:
                uc.append({'Tenor': lbl, 'Yield': float(df['Value'].iloc[-1])})
        if len(uc) >= 3:
            fig2 = go.Figure(go.Scatter(x=[r['Tenor'] for r in uc], y=[r['Yield'] for r in uc],
                                        mode='lines+markers', line=dict(color=T['amber'], width=3),
                                        marker=dict(size=8, color=T['amber']),
                                        fill='tozeroy', fillcolor='rgba(255,179,0,0.1)'))
            fig2.update_layout(title='US Treasury Yield Curve',
                               paper_bgcolor=T['bg'], plot_bgcolor=T['panel'],
                               font=dict(color=T['white'], family='monospace'),
                               height=300, margin=dict(t=30))
            st.plotly_chart(fig2, use_container_width=True)
    except: pass

    st.caption("Usage: `WB`  — World bond yields  |  Data: FRED + yfinance")


# ══════════════════════════════════════════════════════════════════════════════
# 18. OAS — OPTION-ADJUSTED SPREAD
# ══════════════════════════════════════════════════════════════════════════════

OAS_SERIES = [
    ('IG Corp',     'BAMLC0A0CM',   'ICE BofA US Corporate Master OAS'),
    ('HY (High Yield)', 'BAMLH0A0HYM2', 'ICE BofA US High Yield Master II OAS'),
    ('AAA',         'BAMLC0A1CAAA', 'ICE BofA AAA US Corporate OAS'),
    ('AA',          'BAMLC0A2CAA',  'ICE BofA AA US Corporate OAS'),
    ('A',           'BAMLC0A3CA',   'ICE BofA Single-A US Corporate OAS'),
    ('BBB',         'BAMLC0A4CBBB', 'ICE BofA BBB US Corporate OAS'),
    ('BB',          'BAMLH0A1HYBB', 'ICE BofA BB US High Yield OAS'),
    ('B',           'BAMLH0A2HYB',  'ICE BofA Single-B US High Yield OAS'),
]
OAS_ALIASES = {
    'IG': 'IG Corp', 'CORP': 'IG Corp', 'IG CORP': 'IG Corp',
    'HY': 'HY (High Yield)', 'HIGHYIELD': 'HY (High Yield)', 'HIGH YIELD': 'HY (High Yield)',
}

def cmd_oas(parts: list, api_keys: dict):
    """OAS [sector] — Option-Adjusted Spread dashboard.

    Without args: shows all ICE BofA OAS sectors.
    With sector arg: focuses on that sector with larger chart.
      Examples: OAS IG, OAS HY, OAS AAA, OAS BBB, OAS BB
    """
    label_to_sid = {label: sid for label, sid, _ in OAS_SERIES}
    sid_to_label = {sid: label for label, sid, _ in OAS_SERIES}

    sector_filter = None
    if len(parts) >= 2:
        raw = ' '.join(parts[1:]).upper().strip()
        if raw in OAS_ALIASES:
            sector_filter = OAS_ALIASES[raw]
        elif raw in {l.upper() for l in label_to_sid}:
            sector_filter = next(l for l in label_to_sid if l.upper() == raw)
        else:
            st.error(f"Unknown OAS sector: '{raw}' — available: IG, HY, AAA, AA, A, BBB, BB, B")
            return

    header = f"📈  OAS — {'OPTION-ADJUSTED SPREAD' if not sector_filter else sector_filter.upper()}"
    st.markdown(f"<div class='term-header'>{header}</div>", unsafe_allow_html=True)
    st.markdown(
        f"<div style='color:{T['muted']};font-family:monospace;font-size:11px;margin-bottom:8px'>"
        f"ICE BofA Index OAS — spread vs spot Treasury curve (bps)</div>",
        unsafe_allow_html=True)

    if sector_filter:
        rows = []
        for label, sid, desc in OAS_SERIES:
            if label != sector_filter:
                continue
            try:
                df = _fred_fetch(sid, api_keys, limit=30)
                if not df.empty:
                    val = float(df['Value'].iloc[-1])
                    pv = float(df['Value'].iloc[-2]) if len(df) > 1 else val
                    rows.append({'Sector': label, 'OAS': val, 'Chg': val - pv, 'Date': str(df['Date'].iloc[-1])[:10]})
                else:
                    rows.append({'Sector': label, 'OAS': None, 'Chg': None, 'Date': '—'})
            except:
                rows.append({'Sector': label, 'OAS': None, 'Chg': None, 'Date': '—'})

        if rows and rows[0]['OAS'] is not None:
            r = rows[0]
            arrow = '▲' if r['Chg'] >= 0 else '▼'
            clr = T['red'] if r['Chg'] >= 0 else T['green']
            c1, c2, c3 = st.columns(3)
            c1.metric("OAS (bps)", f"{r['OAS']:.0f}", f"{arrow} {r['Chg']:+.0f} bps")
            c2.metric("Date", r['Date'])
            c3.markdown(
                f"<div style='color:{T['muted']};font-family:monospace;font-size:11px;padding-top:18px'>"
                f"{'⚠️  Spreads widening — credit risk increasing' if r['Chg'] > 0 else '✅  Spreads narrowing — credit improving'}</div>",
                unsafe_allow_html=True)

        # Full history chart for the filtered sector
        sid = label_to_sid[sector_filter]
        df = _fred_fetch(sid, api_keys, limit=750)
        if not df.empty:
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=df['Date'], y=df['Value'], mode='lines',
                                     line=dict(color=T['blue'], width=2), name=sector_filter))
            fig.update_layout(title=f'{sector_filter} OAS History (bps)',
                              paper_bgcolor=T['bg'], plot_bgcolor=T['panel'],
                              font=dict(color=T['white'], family='monospace'),
                              height=400, margin=dict(t=40))
            st.plotly_chart(fig, use_container_width=True)
    else:
        rows = []
        for label, sid, desc in OAS_SERIES:
            try:
                df = _fred_fetch(sid, api_keys, limit=30)
                if not df.empty:
                    val = float(df['Value'].iloc[-1])
                    pv = float(df['Value'].iloc[-2]) if len(df) > 1 else val
                    rows.append({'Sector': label, 'OAS': val, 'Chg': val - pv, 'Date': str(df['Date'].iloc[-1])[:10]})
                else:
                    rows.append({'Sector': label, 'OAS': None, 'Chg': None, 'Date': '—'})
            except:
                rows.append({'Sector': label, 'OAS': None, 'Chg': None, 'Date': '—'})

        c1, c2, c3, c4 = st.columns(4)
        cols_cycle = [c1, c2, c3, c4]
        for i, r in enumerate(rows):
            col = cols_cycle[i % 4]
            if r['OAS'] is not None:
                arrow = '▲' if r['Chg'] >= 0 else '▼'
                color = T['red'] if r['Chg'] >= 0 else T['green']
                col.markdown(
                    f"<div class='term-panel' style='padding:8px;text-align:center'>"
                    f"<div style='color:{T['amber']};font-family:monospace;font-weight:bold;font-size:11px'>{r['Sector']}</div>"
                    f"<div style='color:{T['white']};font-family:monospace;font-size:13px'>{r['OAS']:.0f} bps</div>"
                    f"<div style='color:{color};font-family:monospace;font-size:11px'>{arrow} {abs(r['Chg']):.0f} bps</div>"
                    f"</div>", unsafe_allow_html=True)
            else:
                col.markdown(
                    f"<div class='term-panel' style='padding:8px;text-align:center'>"
                    f"<div style='color:{T['amber']};font-family:monospace;font-size:11px'>{r['Sector']}</div>"
                    f"<div style='color:{T['muted']};font-family:monospace;font-size:13px'>—</div>"
                    f"</div>", unsafe_allow_html=True)

        series_to_plot = [('IG Corp', 'BAMLC0A0CM'), ('High Yield', 'BAMLH0A0HYM2')]
        fig = go.Figure()
        colors = [T['blue'], T['red']]
        for (lbl, sid), clr in zip(series_to_plot, colors):
            df = _fred_fetch(sid, api_keys, limit=500)
            if not df.empty:
                fig.add_trace(go.Scatter(x=df['Date'], y=df['Value'], mode='lines',
                                         name=lbl, line=dict(color=clr, width=2)))
        if fig.data:
            fig.update_layout(title='ICE BofA OAS — IG vs High Yield (bps)',
                              paper_bgcolor=T['bg'], plot_bgcolor=T['panel'],
                              font=dict(color=T['white'], family='monospace'),
                              height=380, legend=dict(orientation='h'),
                              margin=dict(t=40))
            st.plotly_chart(fig, use_container_width=True)

        df_disp = pd.DataFrame([r for r in rows if r['OAS'] is not None])
        if not df_disp.empty:
            st.markdown("**OAS by Rating**")
            st.dataframe(df_disp, use_container_width=True, hide_index=True)

    st.caption("Usage: `OAS`  |  `OAS IG`  |  `OAS HY`  |  `OAS AAA`  |  Data: FRED (ICE BofA)  |  Spreads widening (▲) = credit risk increasing")


# ══════════════════════════════════════════════════════════════════════════════
# 19. OASD — OPTION-ADJUSTED SPREAD DURATION
# ══════════════════════════════════════════════════════════════════════════════

OASD_SERIES = [
    ('IG Corp',      'BAMLC0A0CM',   'ICE BofA US Corp OAS'),
    ('1-3Y IG',      'BAMLC1A0C13Y', 'ICE BofA 1-3Y US Corp OAS'),
    ('3-5Y IG',      'BAMLC2A0C35Y', 'ICE BofA 3-5Y US Corp OAS'),
    ('5-7Y IG',      'BAMLC3A0C57Y', 'ICE BofA 5-7Y US Corp OAS'),
    ('7-10Y IG',     'BAMLC4A0C710Y','ICE BofA 7-10Y US Corp OAS'),
    ('10-15Y IG',    'BAMLC7A0C1015Y','ICE BofA 10-15Y US Corp OAS'),
    ('15+Y IG',      'BAMLC8A0C15PY','ICE BofA 15+ US Corp OAS'),
    ('HY (High Yield)', 'BAMLH0A0HYM2', 'ICE BofA US HY OAS'),
]
OASD_ALIASES = {
    'IG': 'IG Corp',
    'HY': 'HY (High Yield)', 'HIGHYIELD': 'HY (High Yield)', 'HIGH YIELD': 'HY (High Yield)',
    '1-3': '1-3Y IG', '1-3Y': '1-3Y IG', 'SHORT': '1-3Y IG',
    '3-5': '3-5Y IG', '3-5Y': '3-5Y IG',
    '5-7': '5-7Y IG', '5-7Y': '5-7Y IG',
    '7-10': '7-10Y IG', '7-10Y': '7-10Y IG', 'MEDIUM': '7-10Y IG',
    '10-15': '10-15Y IG', '10-15Y': '10-15Y IG', 'LONG': '10-15Y IG',
    '15+': '15+Y IG', '15+Y': '15+Y IG', '15PLUS': '15+Y IG',
}

def cmd_oasd(parts: list, api_keys: dict):
    """OASD [bucket] — Option-Adjusted Spread Duration dashboard.

    Without args: shows all maturity buckets.
    With bucket arg: focuses on that bucket with larger chart.
      Examples: OASD IG, OASD HY, OASD 1-3Y, OASD 10-15Y, OASD SHORT
    """
    label_to_sid = {label: sid for label, sid, _ in OASD_SERIES}

    bucket_filter = None
    if len(parts) >= 2:
        raw = ' '.join(parts[1:]).upper().strip()
        if raw in OASD_ALIASES:
            bucket_filter = OASD_ALIASES[raw]
        elif raw in {l.upper() for l in label_to_sid}:
            bucket_filter = next(l for l in label_to_sid if l.upper() == raw)
        else:
            st.error(f"Unknown OASD bucket: '{raw}' — available: IG, HY, 1-3Y, 3-5Y, 5-7Y, 7-10Y, 10-15Y, 15+Y")
            return

    header = f"📏  OASD — {'OAS DURATION' if not bucket_filter else bucket_filter.upper()}"
    st.markdown(f"<div class='term-header'>{header}</div>", unsafe_allow_html=True)
    st.markdown(
        f"<div style='color:{T['muted']};font-family:monospace;font-size:11px;margin-bottom:8px'>"
        f"ICE BofA OAS by Maturity Bucket — spread & effective duration profile</div>",
        unsafe_allow_html=True)

    rows = []
    for label, sid, desc in OASD_SERIES:
        if bucket_filter and label != bucket_filter:
            continue
        try:
            df = _fred_fetch(sid, api_keys, limit=30)
            if not df.empty:
                val = float(df['Value'].iloc[-1])
                pv = float(df['Value'].iloc[-2]) if len(df) > 1 else val
                rows.append({'Bucket': label, 'OAS (bps)': round(val, 1),
                             'Chg (bps)': round(val - pv, 1),
                             'Date': str(df['Date'].iloc[-1])[:10]})
            else:
                rows.append({'Bucket': label, 'OAS (bps)': None, 'Chg (bps)': None, 'Date': '—'})
        except:
            rows.append({'Bucket': label, 'OAS (bps)': None, 'Chg (bps)': None, 'Date': '—'})

    if bucket_filter:
        if rows and rows[0]['OAS (bps)'] is not None:
            r = rows[0]
            arrow = '▲' if r['Chg (bps)'] >= 0 else '▼'
            clr = T['red'] if r['Chg (bps)'] >= 0 else T['green']
            c1, c2 = st.columns(2)
            c1.metric("OAS (bps)", f"{r['OAS (bps)']:.0f}", f"{arrow} {abs(r['Chg (bps)']):+.1f} bps")
            desc = next((d for l, s, d in OASD_SERIES if l == bucket_filter), '')
            c2.markdown(
                f"<div style='color:{T['muted']};font-family:monospace;font-size:11px;padding-top:18px'>{desc}</div>",
                unsafe_allow_html=True)

        sid = label_to_sid[bucket_filter]
        df = _fred_fetch(sid, api_keys, limit=750)
        if not df.empty:
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=df['Date'], y=df['Value'], mode='lines',
                                     line=dict(color=T['blue'], width=2), name=bucket_filter))
            fig.update_layout(title=f'{bucket_filter} OAS History (bps)',
                              paper_bgcolor=T['bg'], plot_bgcolor=T['panel'],
                              font=dict(color=T['white'], family='monospace'),
                              height=400, margin=dict(t=40))
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.markdown("**OAS by Maturity Bucket**")
        c1, c2, c3, c4 = st.columns(4)
        bucket_cols = [c1, c2, c3, c4]
        for i, r in enumerate(rows[:8]):
            col = bucket_cols[i % 4]
            if r['OAS (bps)'] is not None:
                arrow = '▲' if r['Chg (bps)'] >= 0 else '▼'
                color = T['red'] if r['Chg (bps)'] >= 0 else T['green']
                col.markdown(
                    f"<div class='term-panel' style='padding:6px;text-align:center'>"
                    f"<div style='color:{T['amber']};font-family:monospace;font-weight:bold;font-size:10px'>{r['Bucket']}</div>"
                    f"<div style='color:{T['white']};font-family:monospace;font-size:12px'>{r['OAS (bps)']:.0f} bps</div>"
                    f"<div style='color:{color};font-family:monospace;font-size:10px'>{arrow} {abs(r['Chg (bps)']):.0f} bps</div>"
                    f"</div>", unsafe_allow_html=True)

        maturity_order = ['1-3Y IG', '3-5Y IG', '5-7Y IG', '7-10Y IG', '10-15Y IG', '15+Y IG']
        dur_vals = []
        for m in maturity_order:
            for r in rows:
                if r['Bucket'] == m and r['OAS (bps)'] is not None:
                    dur_vals.append({'Maturity': m, 'OAS': r['OAS (bps)']})
                    break
        if dur_vals:
            fig = go.Figure(go.Bar(x=[d['Maturity'] for d in dur_vals],
                                   y=[d['OAS'] for d in dur_vals],
                                   marker_color=T['blue'],
                                   text=[f"{d['OAS']:.0f}" for d in dur_vals],
                                   textposition='outside'))
            fig.update_layout(title='IG OAS by Maturity Bucket (bps)',
                              paper_bgcolor=T['bg'], plot_bgcolor=T['panel'],
                              font=dict(color=T['white'], family='monospace'),
                              height=350, xaxis_tickangle=-30, margin=dict(b=60))
            st.plotly_chart(fig, use_container_width=True)

        fig2 = go.Figure()
        plot_pairs = [('1-3Y IG', 'BAMLC1A0C13Y'), ('10-15Y IG', 'BAMLC7A0C1015Y')]
        plot_colors = [T['green'], T['red']]
        for (lbl, sid), clr in zip(plot_pairs, plot_colors):
            df = _fred_fetch(sid, api_keys, limit=500)
            if not df.empty:
                fig2.add_trace(go.Scatter(x=df['Date'], y=df['Value'], mode='lines',
                                          name=lbl, line=dict(color=clr, width=2)))
        if fig2.data:
            fig2.update_layout(title='OAS — Short vs Long Duration',
                               paper_bgcolor=T['bg'], plot_bgcolor=T['panel'],
                               font=dict(color=T['white'], family='monospace'),
                               height=350, legend=dict(orientation='h'),
                               margin=dict(t=40))
            st.plotly_chart(fig2, use_container_width=True)

        df_disp = pd.DataFrame([r for r in rows if r['OAS (bps)'] is not None])
        if not df_disp.empty:
            st.dataframe(df_disp, use_container_width=True, hide_index=True)

    st.caption("Usage: `OASD`  |  `OASD IG`  |  `OASD HY`  |  `OASD 1-3Y`  |  Data: FRED (ICE BofA)  |  Longer maturities = higher duration risk")
