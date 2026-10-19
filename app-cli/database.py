"""
database.py – SQLite database initialisation, user authentication, and strategy CRUD.
"""
import sqlite3, hashlib, os, time
import streamlit as st

DB_PATH = 'users.db'
UPLOADS_DIR = './uploads/'


def _db():
    return sqlite3.connect(DB_PATH)

def init_database():
    with _db() as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS strategies (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            description_line1 TEXT, description_line2 TEXT,
            description_line3 TEXT, description_line4 TEXT,
            csv_filename TEXT NOT NULL, created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, is_default BOOLEAN DEFAULT 0,
            FOREIGN KEY (created_by) REFERENCES users(id))''')
        c.execute('''CREATE TABLE IF NOT EXISTS user_strategies (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            strategy_id INTEGER NOT NULL, added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_favorite BOOLEAN DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (strategy_id) REFERENCES strategies(id),
            UNIQUE(user_id, strategy_id))''')
        c.execute('''CREATE TABLE IF NOT EXISTS user_api_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            service TEXT NOT NULL,
            api_key TEXT NOT NULL DEFAULT '',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            UNIQUE(user_id, service))''')

        # Migration: rebuild if table was created with a wrong/old schema
        existing_cols = {row[1] for row in c.execute("PRAGMA table_info(user_api_keys)").fetchall()}
        if 'service' not in existing_cols:
            c.execute("DROP TABLE user_api_keys")
            c.execute('''CREATE TABLE user_api_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                service TEXT NOT NULL,
                api_key TEXT NOT NULL DEFAULT '',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id),
                UNIQUE(user_id, service))''')
        c.execute('''CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER NOT NULL,
            recipient_id INTEGER NOT NULL,
            subject TEXT NOT NULL DEFAULT '',
            body TEXT NOT NULL DEFAULT '',
            attachment_filename TEXT,
            attachment_orig_name TEXT,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            read_at TIMESTAMP,
            deleted_by_sender BOOLEAN DEFAULT 0,
            deleted_by_recipient BOOLEAN DEFAULT 0,
            FOREIGN KEY (sender_id) REFERENCES users(id),
            FOREIGN KEY (recipient_id) REFERENCES users(id))''')
        c.execute('''CREATE TABLE IF NOT EXISTS price_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            ticker TEXT NOT NULL,
            pct_interval REAL NOT NULL,
            baseline_price REAL,
            last_triggered_multiple INTEGER DEFAULT 0,
            last_reset_date TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_active BOOLEAN DEFAULT 1,
            FOREIGN KEY (user_id) REFERENCES users(id),
            UNIQUE(user_id, ticker))''')
        c.execute('''CREATE TABLE IF NOT EXISTS watchlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            ticker TEXT NOT NULL,
            label TEXT DEFAULT '',
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            UNIQUE(user_id, ticker))''')
        c.execute('''CREATE TABLE IF NOT EXISTS pnl_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            ticker TEXT NOT NULL,
            quantity REAL NOT NULL,
            cost_basis REAL NOT NULL,
            currency TEXT DEFAULT 'USD',
            notes TEXT DEFAULT '',
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            UNIQUE(user_id, ticker))''')
        conn.commit()

        if c.execute("SELECT COUNT(*) FROM strategies WHERE is_default=1").fetchone()[0] == 0:
            defaults = [
                ("Volatility Risk Premium",
                 "Allocates funds to Short VIX ETF and Treasury ETF.",
                 "Captures returns via Short VIX ETF during normal market conditions.",
                 "Shifts to Treasury ETF when market volatility rises.",
                 "Performance evaluated via historical backtesting.", "sample.csv"),
                ("Strategy Asset Allocation",
                 "Asset allocation strategy focusing on optimal portfolio distribution.",
                 "Diversifies across multiple asset classes to maximise returns.",
                 "Uses modern portfolio theory principles for allocation decisions.",
                 "Regular rebalancing to maintain target allocations.", "sample2.csv"),
                ("Cross Sectional Mean Reversion LGLV",
                 "Cross sectional mean reversion across 100 stocks.",
                 "Identifies underperforming stocks with expectation of rebound.",
                 "Uses paper trading approach in Interactive Brokers.",
                 "Compares returns against benchmark SPY index.", "sample3.csv"),
                ("Long/Short, dollar neutral on LGLV",
                 "Long/short equity strategy with dollar neutral approach.",
                 "Based on mean reversion principles over short periods.",
                 "Simulated trading using real-time market data.",
                 "Risk management through portfolio diversification.", "sample4.csv"),
                ("Intraday Multiple FX",
                 "FX multiple pairs intraday trading strategy.",
                 "Focuses on currency pair correlations and momentum.",
                 "High-frequency approach with tight risk controls.",
                 "Leverages technical indicators for entry/exit signals.", "sample5.csv"),
                ("Intraday Multiple FX cTrader",
                 "cTrader based FX multiple pairs strategy.",
                 "Advanced algorithmic trading with cTrader platform.",
                 "Real-time execution with automated risk management.",
                 "Multi-currency portfolio optimisation.", "sample6.csv"),
            ]
            for s in defaults:
                c.execute('''INSERT INTO strategies
                    (name,description_line1,description_line2,description_line3,
                     description_line4,csv_filename,is_default) VALUES (?,?,?,?,?,?,1)''', s)
            conn.commit()

            row = c.execute("SELECT id FROM users WHERE email=?", ("chun.wing.man@gmail.com",)).fetchone()
            if row:
                uid = row[0]
                for (sid,) in c.execute("SELECT id FROM strategies WHERE is_default=1").fetchall():
                    try:
                        c.execute("INSERT INTO user_strategies (user_id,strategy_id) VALUES (?,?)", (uid, sid))
                    except sqlite3.IntegrityError:
                        pass
                conn.commit()

def create_user(email, password):
    try:
        with _db() as conn:
            c = conn.cursor()
            if c.execute('SELECT id FROM users WHERE email=?', (email,)).fetchone():
                return False, "User already exists"
            c.execute('INSERT INTO users (email,password_hash) VALUES (?,?)',
                      (email, hashlib.sha256(password.encode()).hexdigest()))
            conn.commit()
        return True, "User created successfully"
    except Exception as e:
        return False, str(e)

def verify_user(email, password):
    try:
        with _db() as conn:
            row = conn.execute('SELECT id,password_hash FROM users WHERE email=?', (email,)).fetchone()
        if not row:
            return False, "User not found", None
        uid, h = row
        if h == hashlib.sha256(password.encode()).hexdigest():
            return True, "Login successful", uid
        return False, "Invalid password", None
    except Exception as e:
        return False, str(e), None

def get_user_strategies(user_id):
    try:
        with _db() as conn:
            rows = conn.execute('''
                SELECT s.id,s.name,s.description_line1,s.description_line2,
                       s.description_line3,s.description_line4,s.csv_filename,
                       s.is_default,us.is_favorite
                FROM strategies s JOIN user_strategies us ON s.id=us.strategy_id
                WHERE us.user_id=? ORDER BY us.is_favorite DESC, s.name''', (user_id,)).fetchall()
        return [{'id':r[0],'name':r[1],'descriptions':[r[2],r[3],r[4],r[5]],
                 'csv_filename':r[6],'is_default':bool(r[7]),'is_favorite':bool(r[8])} for r in rows]
    except Exception as e:
        st.error(f"Error getting strategies: {e}"); return []

def add_strategy_to_user(user_id, data, uploaded_file):
    try:
        if not uploaded_file:
            return False, "No file uploaded", None
        ts = int(time.time())
        ext = os.path.splitext(uploaded_file.name)[1]
        fname = f"user_{user_id}_{ts}{ext}"
        with open(f'./uploads/{fname}', 'wb') as f:
            f.write(uploaded_file.getbuffer())
        with _db() as conn:
            c = conn.cursor()
            c.execute('''INSERT INTO strategies
                (name,description_line1,description_line2,description_line3,
                 description_line4,csv_filename,created_by,is_default)
                VALUES (?,?,?,?,?,?,?,0)''',
                (data['name'],data['description_line1'],data['description_line2'],
                 data['description_line3'],data['description_line4'],fname,user_id))
            sid = c.lastrowid
            c.execute("INSERT INTO user_strategies (user_id,strategy_id) VALUES (?,?)", (user_id, sid))
            conn.commit()
        return True, "Strategy added successfully", sid
    except Exception as e:
        return False, str(e), None

def update_strategy(strategy_id, data, uploaded_file=None):
    try:
        with _db() as conn:
            c = conn.cursor()
            cur = c.execute('SELECT csv_filename,created_by FROM strategies WHERE id=?', (strategy_id,)).fetchone()
            cur_fname, uid = cur
            if uploaded_file:
                if cur_fname and not cur_fname.startswith('sample'):
                    fp = f'./uploads/{cur_fname}'
                    if os.path.exists(fp): os.remove(fp)
                ts = int(time.time())
                ext = os.path.splitext(uploaded_file.name)[1]
                new_fname = f"user_{uid}_{ts}{ext}"
                with open(f'./uploads/{new_fname}', 'wb') as f:
                    f.write(uploaded_file.getbuffer())
            else:
                new_fname = cur_fname
            c.execute('''UPDATE strategies SET name=?,description_line1=?,description_line2=?,
                description_line3=?,description_line4=?,csv_filename=? WHERE id=?''',
                (data['name'],data['description_line1'],data['description_line2'],
                 data['description_line3'],data['description_line4'],new_fname,strategy_id))
            conn.commit()
        return True, "Strategy updated successfully"
    except Exception as e:
        return False, str(e)

def delete_strategy_from_user(user_id, strategy_id):
    try:
        with _db() as conn:
            c = conn.cursor()
            row = c.execute('SELECT is_default,csv_filename FROM strategies WHERE id=?', (strategy_id,)).fetchone()
            if not row: return False, "Strategy not found"
            if row[0]: return False, "Cannot delete default strategy"
            c.execute('DELETE FROM user_strategies WHERE user_id=? AND strategy_id=?', (user_id, strategy_id))
            if c.execute('SELECT COUNT(*) FROM user_strategies WHERE strategy_id=?', (strategy_id,)).fetchone()[0] == 0:
                c.execute('DELETE FROM strategies WHERE id=?', (strategy_id,))
                fname = row[1]
                if fname and not fname.startswith('sample'):
                    fp = f'./uploads/{fname}'
                    if os.path.exists(fp): os.remove(fp)
            conn.commit()
        return True, "Strategy removed successfully"
    except Exception as e:
        return False, str(e)

def toggle_favorite(user_id, strategy_id):
    try:
        with _db() as conn:
            conn.execute('''UPDATE user_strategies SET is_favorite=NOT is_favorite
                WHERE user_id=? AND strategy_id=?''', (user_id, strategy_id))
            conn.commit()
        return True, "Favourite status updated"
    except Exception as e:
        return False, str(e)

# ── API key management ─────────────────────────────────────────────────────────

KNOWN_SERVICES = ('alpha_vantage', 'fmp', 'fred', 'polygon', 'openai_key',
                  'openai_url', 'openai_model',
                  'alpaca_key', 'alpaca_secret',
                  'gmail_user', 'gmail_pass',
                  'newsapi_key', 'finnhub')

def get_user_api_keys(user_id):
    """Return a dict of {service: api_key} for the given user.
    Any services not yet saved default to empty string."""
    keys = {s: '' for s in KNOWN_SERVICES}
    try:
        with _db() as conn:
            rows = conn.execute(
                'SELECT service, api_key FROM user_api_keys WHERE user_id=?',
                (user_id,)
            ).fetchall()
        for service, api_key in rows:
            if service in keys:
                keys[service] = api_key
    except Exception as e:
        st.error(f"Error loading API keys: {e}")
    return keys

def save_user_api_keys(user_id, keys: dict):
    """Upsert each service key for the given user."""
    try:
        with _db() as conn:
            c = conn.cursor()
            for service in KNOWN_SERVICES:
                api_key = keys.get(service, '')
                c.execute(
                    '''INSERT INTO user_api_keys (user_id, service, api_key, updated_at)
                       VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                       ON CONFLICT(user_id, service)
                       DO UPDATE SET api_key=excluded.api_key,
                                     updated_at=CURRENT_TIMESTAMP''',
                    (user_id, service, api_key))
            conn.commit()
        return True, "API keys saved"
    except Exception as e:
        return False, str(e)

# ── Messaging ──────────────────────────────────────────────────────────────────

def lookup_user_by_email(email: str):
    """Return (id, email) for the given email, or None if not found."""
    try:
        with _db() as conn:
            row = conn.execute('SELECT id, email FROM users WHERE email=?', (email,)).fetchone()
        return {'id': row[0], 'email': row[1]} if row else None
    except Exception as e:
        st.error(f"User lookup error: {e}"); return None

def send_message(sender_id: int, recipient_email: str, subject: str,
                 body: str, uploaded_file=None):
    """Send a message. Returns (ok, msg, message_id)."""
    try:
        recipient = lookup_user_by_email(recipient_email.strip())
        if not recipient:
            return False, f"No user found with email '{recipient_email}'", None

        att_fname = att_orig = None
        if uploaded_file:
            ts = int(time.time())
            ext = os.path.splitext(uploaded_file.name)[1]
            att_fname = f"msg_{sender_id}_{ts}{ext}"
            att_orig  = uploaded_file.name
            with open(f'{UPLOADS_DIR}{att_fname}', 'wb') as f:
                f.write(uploaded_file.getbuffer())

        with _db() as conn:
            c = conn.cursor()
            c.execute('''INSERT INTO messages
                (sender_id, recipient_id, subject, body,
                 attachment_filename, attachment_orig_name)
                VALUES (?,?,?,?,?,?)''',
                (sender_id, recipient['id'], subject, body, att_fname, att_orig))
            mid = c.lastrowid
            conn.commit()
        return True, "Message sent", mid
    except Exception as e:
        return False, str(e), None

def get_inbox(user_id: int) -> list:
    """Return messages received by user_id, newest first."""
    try:
        with _db() as conn:
            rows = conn.execute('''
                SELECT m.id, u.email AS sender_email, m.subject, m.body,
                       m.attachment_filename, m.attachment_orig_name,
                       m.sent_at, m.read_at
                FROM messages m
                JOIN users u ON m.sender_id = u.id
                WHERE m.recipient_id=? AND m.deleted_by_recipient=0
                ORDER BY m.sent_at DESC''', (user_id,)).fetchall()
        return [{'id':r[0],'sender':r[1],'subject':r[2],'body':r[3],
                 'attachment_filename':r[4],'attachment_orig_name':r[5],
                 'sent_at':r[6],'read_at':r[7],
                 'unread': r[7] is None} for r in rows]
    except Exception as e:
        st.error(f"Inbox error: {e}"); return []

def get_sent(user_id: int) -> list:
    """Return messages sent by user_id, newest first."""
    try:
        with _db() as conn:
            rows = conn.execute('''
                SELECT m.id, u.email AS recipient_email, m.subject, m.body,
                       m.attachment_filename, m.attachment_orig_name,
                       m.sent_at, m.read_at
                FROM messages m
                JOIN users u ON m.recipient_id = u.id
                WHERE m.sender_id=? AND m.deleted_by_sender=0
                ORDER BY m.sent_at DESC''', (user_id,)).fetchall()
        return [{'id':r[0],'recipient':r[1],'subject':r[2],'body':r[3],
                 'attachment_filename':r[4],'attachment_orig_name':r[5],
                 'sent_at':r[6],'read_at':r[7]} for r in rows]
    except Exception as e:
        st.error(f"Sent error: {e}"); return []

def mark_message_read(message_id: int, user_id: int):
    """Mark a message as read (only recipient can mark)."""
    try:
        with _db() as conn:
            conn.execute('''UPDATE messages SET read_at=CURRENT_TIMESTAMP
                WHERE id=? AND recipient_id=? AND read_at IS NULL''',
                (message_id, user_id))
            conn.commit()
    except: pass

def delete_message(message_id: int, user_id: int):
    """Soft-delete: flag the message deleted for this user's view."""
    try:
        with _db() as conn:
            c = conn.cursor()
            row = c.execute('SELECT sender_id, recipient_id FROM messages WHERE id=?',
                            (message_id,)).fetchone()
            if not row: return False, "Message not found"
            if row[0] == user_id:
                c.execute('UPDATE messages SET deleted_by_sender=1 WHERE id=?', (message_id,))
            elif row[1] == user_id:
                c.execute('UPDATE messages SET deleted_by_recipient=1 WHERE id=?', (message_id,))
            else:
                return False, "Not authorised"
            conn.commit()
        return True, "Deleted"
    except Exception as e:
        return False, str(e)

def get_unread_count(user_id: int) -> int:
    """Return number of unread messages for user."""
    try:
        with _db() as conn:
            row = conn.execute('''SELECT COUNT(*) FROM messages
                WHERE recipient_id=? AND read_at IS NULL AND deleted_by_recipient=0''',
                (user_id,)).fetchone()
        return row[0] if row else 0
    except: return 0

# ── Price alert management ─────────────────────────────────────────────────────

def add_price_alert(user_id: int, ticker: str, pct_interval: float, baseline_price: float):
    """Add or update a price alert for a user/ticker pair."""
    try:
        today = __import__('datetime').date.today().isoformat()
        with _db() as conn:
            conn.execute('''
                INSERT INTO price_alerts
                    (user_id, ticker, pct_interval, baseline_price,
                     last_triggered_multiple, last_reset_date, is_active)
                VALUES (?,?,?,?,0,?,1)
                ON CONFLICT(user_id, ticker) DO UPDATE SET
                    pct_interval=excluded.pct_interval,
                    baseline_price=excluded.baseline_price,
                    last_triggered_multiple=0,
                    last_reset_date=excluded.last_reset_date,
                    is_active=1''',
                (user_id, ticker.upper(), pct_interval, baseline_price, today))
            conn.commit()
        return True, f"Alert added: {ticker.upper()} every {pct_interval}%"
    except Exception as e:
        return False, str(e)

def remove_price_alert(user_id: int, ticker: str):
    """Deactivate all alerts for user/ticker."""
    try:
        with _db() as conn:
            c = conn.cursor()
            c.execute('''UPDATE price_alerts SET is_active=0
                WHERE user_id=? AND ticker=?''', (user_id, ticker.upper()))
            removed = c.rowcount
            conn.commit()
        if removed:
            return True, f"Alert removed for {ticker.upper()}"
        return False, f"No active alert found for {ticker.upper()}"
    except Exception as e:
        return False, str(e)

def get_user_alerts(user_id: int) -> list:
    """Return all active alerts for a user."""
    try:
        with _db() as conn:
            rows = conn.execute('''
                SELECT id, ticker, pct_interval, baseline_price,
                       last_triggered_multiple, last_reset_date, created_at
                FROM price_alerts
                WHERE user_id=? AND is_active=1
                ORDER BY ticker''', (user_id,)).fetchall()
        return [{'id': r[0], 'ticker': r[1], 'pct_interval': r[2],
                 'baseline_price': r[3], 'last_triggered_multiple': r[4],
                 'last_reset_date': r[5], 'created_at': r[6]} for r in rows]
    except Exception as e:
        return []

def get_all_active_alerts() -> list:
    """Return all active alerts across all users (for the scheduler)."""
    try:
        with _db() as conn:
            rows = conn.execute('''
                SELECT pa.id, pa.user_id, u.email, pa.ticker,
                       pa.pct_interval, pa.baseline_price,
                       pa.last_triggered_multiple, pa.last_reset_date
                FROM price_alerts pa
                JOIN users u ON pa.user_id = u.id
                WHERE pa.is_active=1''').fetchall()
        return [{'id': r[0], 'user_id': r[1], 'email': r[2], 'ticker': r[3],
                 'pct_interval': r[4], 'baseline_price': r[5],
                 'last_triggered_multiple': r[6], 'last_reset_date': r[7]} for r in rows]
    except Exception as e:
        return []

def update_alert_trigger(alert_id: int, new_multiple: int, today: str):
    """Record that we fired at a given multiple today."""
    try:
        with _db() as conn:
            conn.execute('''UPDATE price_alerts
                SET last_triggered_multiple=?, last_reset_date=?
                WHERE id=?''', (new_multiple, today, alert_id))
            conn.commit()
    except: pass

def reset_alert_daily(alert_id: int, today: str):
    """Reset multiple counter for a new trading day."""
    try:
        with _db() as conn:
            conn.execute('''UPDATE price_alerts
                SET last_triggered_multiple=0, last_reset_date=?
                WHERE id=?''', (today, alert_id))
            conn.commit()
    except: pass

# ── Watchlist ──────────────────────────────────────────────────────────────────

def wl_add(user_id: int, ticker: str, label: str = '') -> tuple:
    try:
        with _db() as conn:
            conn.execute('''INSERT INTO watchlist (user_id, ticker, label)
                VALUES (?,?,?)
                ON CONFLICT(user_id, ticker) DO UPDATE SET label=excluded.label''',
                (user_id, ticker.upper(), label))
            conn.commit()
        return True, f"{ticker.upper()} added to watchlist"
    except Exception as e:
        return False, str(e)

def wl_remove(user_id: int, ticker: str) -> tuple:
    try:
        with _db() as conn:
            c = conn.cursor()
            c.execute('DELETE FROM watchlist WHERE user_id=? AND ticker=?',
                      (user_id, ticker.upper()))
            if c.rowcount == 0:
                return False, f"{ticker.upper()} not in watchlist"
            conn.commit()
        return True, f"{ticker.upper()} removed from watchlist"
    except Exception as e:
        return False, str(e)

def wl_get(user_id: int) -> list:
    try:
        with _db() as conn:
            rows = conn.execute('''SELECT ticker, label, added_at
                FROM watchlist WHERE user_id=? ORDER BY ticker''',
                (user_id,)).fetchall()
        return [{'ticker': r[0], 'label': r[1], 'added_at': r[2]} for r in rows]
    except:
        return []

# ── PnL positions ──────────────────────────────────────────────────────────────

def pnl_add(user_id: int, ticker: str, quantity: float,
            cost_basis: float, notes: str = '') -> tuple:
    try:
        with _db() as conn:
            conn.execute('''INSERT INTO pnl_positions
                (user_id, ticker, quantity, cost_basis, notes)
                VALUES (?,?,?,?,?)
                ON CONFLICT(user_id, ticker) DO UPDATE SET
                    quantity=excluded.quantity,
                    cost_basis=excluded.cost_basis,
                    notes=excluded.notes''',
                (user_id, ticker.upper(), quantity, cost_basis, notes))
            conn.commit()
        return True, f"Position saved: {ticker.upper()}"
    except Exception as e:
        return False, str(e)

def pnl_remove(user_id: int, ticker: str) -> tuple:
    try:
        with _db() as conn:
            c = conn.cursor()
            c.execute('DELETE FROM pnl_positions WHERE user_id=? AND ticker=?',
                      (user_id, ticker.upper()))
            if c.rowcount == 0:
                return False, f"No position found for {ticker.upper()}"
            conn.commit()
        return True, f"{ticker.upper()} position removed"
    except Exception as e:
        return False, str(e)

def pnl_get(user_id: int) -> list:
    try:
        with _db() as conn:
            rows = conn.execute('''SELECT ticker, quantity, cost_basis, notes, added_at
                FROM pnl_positions WHERE user_id=? ORDER BY ticker''',
                (user_id,)).fetchall()
        return [{'ticker': r[0], 'quantity': r[1], 'cost_basis': r[2],
                 'notes': r[3], 'added_at': r[4]} for r in rows]
    except:
        return []