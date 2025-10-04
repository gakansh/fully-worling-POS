#!/usr/bin/env python3

import json
import os
import urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime, timezone
import uuid
import subprocess
import html

# Project base directories
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
STATIC_DIR = os.path.join(BASE_DIR, 'static')
INVOICE_DIR = os.path.join(BASE_DIR, 'invoices')

USERS_FILE = os.path.join(DATA_DIR, 'users.json')
GAMES_FILE = os.path.join(DATA_DIR, 'games.json')
SESSIONS_FILE = os.path.join(DATA_DIR, 'sessions.json')
INVOICE_RECORDS_FILE = os.path.join(DATA_DIR, 'invoice_records.json')
PAYMENTS_FILE = os.path.join(DATA_DIR, 'payments.json')

# Ensure directories exist
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(INVOICE_DIR, exist_ok=True)

def load_json(path, default):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default

def save_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def load_users():
    return load_json(USERS_FILE, {})

def save_users(users):
    save_json(USERS_FILE, users)

def load_games():
    default_games = [
        {"name": "Game A", "requires_controllers": True, "price_per_hour": 100},
        {"name": "Game B", "requires_controllers": False, "price_per_hour": 120},
        {"name": "Game C", "requires_controllers": True, "price_per_hour": 80}
    ]
    g = load_json(GAMES_FILE, None)
    if g is None or not isinstance(g, list):
        save_json(GAMES_FILE, default_games)
        return default_games
    return g

def save_games(games):
    save_json(GAMES_FILE, games)

def load_sessions():
    return load_json(SESSIONS_FILE, {})

def save_sessions(sessions):
    save_json(SESSIONS_FILE, sessions)

def load_invoice_records():
    return load_json(INVOICE_RECORDS_FILE, [])

def save_invoice_records(records):
    save_json(INVOICE_RECORDS_FILE, records)

def load_payments():
    return load_json(PAYMENTS_FILE, [])

def save_payments(payments):
    save_json(PAYMENTS_FILE, payments)

class POSHandler(SimpleHTTPRequestHandler):
    users = load_users()
    games = load_games()
    sessions = load_sessions()

    def _send_json(self, data, status=200):
        encoded = json.dumps(data).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _read_request_json(self):
        length = int(self.headers.get('Content-Length', '0'))
        body = self.rfile.read(length) if length > 0 else b''
        try:
            return json.loads(body.decode('utf-8'))
        except Exception:
            return None

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path.startswith('/api/'):
            if path == '/api/games':
                # Return games with current prices
                self._send_json(POSHandler.games)
                return
            if path == '/api/stations':
                self._handle_get_stations()
                return
            if path == '/api/sessions':
                self._handle_get_sessions()
                return
            if path.startswith('/api/users/'):
                mobile = path[len('/api/users/'):]
                self._handle_get_user(mobile)
                return
            self._send_json({'error': 'Unknown API endpoint'}, 404)
            return

        if path == '/':
            self.path = '/index.html'
        return SimpleHTTPRequestHandler.do_GET(self)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path == '/api/start_session':
            self._handle_start_session()
            return
        if path == '/api/end_session':
            self._handle_end_session()
            return
        if path == '/api/games/update_price':
            self._handle_update_price()
            return
        self._send_json({'error': 'Unknown API endpoint'}, 404)

    def _handle_update_price(self):
        """Update the price_per_hour for a given game."""
        payload = self._read_request_json()
        if not isinstance(payload, dict):
            self._send_json({'error': 'Invalid JSON'}, 400)
            return
        name = payload.get('name')
        new_price = payload.get('price_per_hour')
        if name is None or new_price is None:
            self._send_json({'error': 'Missing name or new price'}, 400)
            return
        found = False
        for g in POSHandler.games:
            if g.get('name') == name:
                try:
                    g['price_per_hour'] = float(new_price)
                except ValueError:
                    self._send_json({'error': 'price must be a number'}, 400)
                    return
                found = True
                break
        if not found:
            self._send_json({'error': 'Game not found'}, 404)
            return
        save_games(POSHandler.games)
        self._send_json({'status': 'ok', 'games': POSHandler.games})

    def _handle_get_stations(self):
        stations = {}
        for letter in ['A','B','C','D','E','F','G']:
            stations[letter] = {'occupied': False, 'session_id': None}
        for sid, sess in POSHandler.sessions.items():
            stations[sess['station']] = {'occupied': True, 'session_id': sid}
        self._send_json(stations)

    def _handle_get_sessions(self):
        lst = list(POSHandler.sessions.values())
        self._send_json(lst)

    def _handle_get_user(self, mobile):
        mobile = mobile.strip()
        if not mobile:
            self._send_json({'error': 'Mobile number required'}, 400)
            return
        user = POSHandler.users.get(mobile)
        if user is None:
            user = {'mobile': mobile, 'wallet': 0.0}
            POSHandler.users[mobile] = user
            save_users(POSHandler.users)
        self._send_json(user)

    def _handle_start_session(self):
        payload = self._read_request_json()
        if not isinstance(payload, dict):
            self._send_json({'error': 'Invalid JSON'}, 400)
            return
        mobile = str(payload.get('mobile', '')).strip()
        station = str(payload.get('station', '')).strip().upper()
        game = str(payload.get('game', '')).strip()
        controllers = int(payload.get('controllers', 0))
        if not mobile or station not in ['A','B','C','D','E','F','G'] or not game:
            self._send_json({'error': 'Missing or invalid fields'}, 400)
            return
        user = POSHandler.users.get(mobile)
        if user is None:
            user = {'mobile': mobile, 'wallet': 0.0}
            POSHandler.users[mobile] = user
            save_users(POSHandler.users)
        for sid, s in POSHandler.sessions.items():
            if s['station'] == station:
                self._send_json({'error': f'Station {station} is occupied'}, 409)
                return
        game_obj = next((g for g in POSHandler.games if g['name'] == game), None)
        if not game_obj:
            self._send_json({'error': 'Unknown game'}, 400)
            return
        if not game_obj.get('requires_controllers', True):
            controllers = 0
        sid = str(uuid.uuid4())
        new_s = {
            'session_id': sid,
            'mobile': mobile,
            'station': station,
            'game': game,
            'controllers': controllers,
            'start_time': datetime.now(timezone.utc).isoformat()
        }
        POSHandler.sessions[sid] = new_s
        save_sessions(POSHandler.sessions)
        self._send_json({'session_id': sid, 'status': 'started'})

    def _calculate_duration_hours(self, start_iso, end_dt):
        try:
            st = datetime.fromisoformat(start_iso)
        except Exception:
            st = end_dt
        diff = end_dt - st
        total_minutes = diff.total_seconds() / 60.0
        if total_minutes < 0:
            total_minutes = 0
        hours = int(total_minutes // 60)
        remainder = total_minutes - hours * 60
        extra = 0
        if remainder > 15:
            extra = 0.5
        return hours + extra

    def _create_invoice_pdf(self, invoice_id, inv):
        os.makedirs(INVOICE_DIR, exist_ok=True)
        html_path = os.path.join(INVOICE_DIR, f"{invoice_id}.html")
        pdf_path = os.path.join(INVOICE_DIR, f"{invoice_id}.pdf")

        def money(v):
            try:
                return f"₹{float(v):.2f}"
            except Exception:
                return str(v)
        def esc(v):
            return html.escape(str(v))

        created = inv.get('date', '')
        rows = [
            ("Invoice ID", invoice_id),
            ("Date", created),
            ("Mobile", inv.get('mobile', '')),
            ("Station", inv.get('station', '')),
            ("Game", inv.get('game', '')),
            ("Controllers", inv.get('controllers', 0)),
            ("Duration (hrs)", f"{float(inv.get('duration_hours', 0)):.2f}"),
            ("Base Cost", money(inv.get('base_cost', 0))),
            ("Food Cost", money(inv.get('food_cost', 0))),
            ("Wallet Used", money(inv.get('wallet_used', 0))),
            ("Total Due", money(inv.get('total_due', 0))),
            ("Loyalty Earned", money(inv.get('loyalty_earned', 0))),
            ("Remaining Wallet", money(inv.get('remaining_wallet', 0))),
        ]
        rows_html = "\n".join(f"<tr><th>{esc(k)}</th><td>{esc(v)}</td></tr>" for k, v in rows)
        html_doc = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Invoice {esc(invoice_id)}</title>
<style>
body {{ font-family: sans-serif; padding: 20px; }}
table {{ width: 100%; border-collapse: collapse; }}
th, td {{ padding: 8px; border: 1px solid #ccc; text-align: left; }}
th {{ background: #f4f4f4; }}
</style>
</head>
<body>
<h2>Invoice {esc(invoice_id)}</h2>
<table>
{rows_html}
</table>
</body>
</html>"""
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html_doc)

        try:
            subprocess.run(
                ["soffice", "--headless", "--convert-to", "pdf", "--outdir", INVOICE_DIR, html_path],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True
            )
            if os.path.exists(pdf_path):
                return pdf_path
        except Exception:
            pass
        return html_path

    def _handle_end_session(self):
        payload = self._read_request_json()
        if not isinstance(payload, dict):
            self._send_json({'error': 'Invalid JSON'}, 400)
            return
        session_id = payload.get('session_id')
        food_cost = float(payload.get('food_cost', 0) or 0)
        use_wallet = bool(payload.get('use_wallet', True))
        if not session_id or session_id not in POSHandler.sessions:
            self._send_json({'error': 'Invalid session id'}, 400)
            return
        sess = POSHandler.sessions.pop(session_id)
        save_sessions(POSHandler.sessions)
        end_dt = datetime.now(timezone.utc)
        duration = self._calculate_duration_hours(sess['start_time'], end_dt)
        game_obj = next((g for g in POSHandler.games if g['name'] == sess['game']), None)
        price = game_obj['price_per_hour'] if game_obj else 100
        if game_obj and not game_obj.get('requires_controllers', True):
            base_cost = duration * price
        else:
            base_cost = duration * price * max(1, sess.get('controllers', 1))

        user = POSHandler.users.get(sess['mobile'], {'mobile': sess['mobile'], 'wallet': 0.0})
        wallet_available = float(user.get('wallet', 0.0))
        wallet_used = 0.0
        total_before = base_cost + food_cost
        if use_wallet and wallet_available > 0:
            wallet_used = min(wallet_available, total_before)
        remaining_due = total_before - wallet_used

        LOYALTY_RATE = 0.10
        loyalty_earned = LOYALTY_RATE * base_cost

        new_wallet = wallet_available - wallet_used + loyalty_earned
        user['wallet'] = round(new_wallet, 2)
        POSHandler.users[user['mobile']] = user
        save_users(POSHandler.users)

        try:
            payments = load_payments()
            payments.append({
                'mobile': sess['mobile'],
                'amount': remaining_due,
                'date': end_dt.astimezone().strftime('%Y-%m-%d %H:%M:%S')
            })
            save_payments(payments)
        except Exception:
            pass

        invoice_id = session_id.replace('-', '')
        invoice = {
            'date': end_dt.astimezone().strftime('%Y-%m-%d %H:%M:%S'),
            'mobile': sess['mobile'],
            'station': sess['station'],
            'game': sess['game'],
            'controllers': sess.get('controllers', 0),
            'duration_hours': duration,
            'base_cost': base_cost,
            'food_cost': food_cost,
            'wallet_used': wallet_used,
            'total_due': remaining_due,
            'loyalty_earned': loyalty_earned,
            'remaining_wallet': user['wallet']
        }

        try:
            recs = load_invoice_records()
            recs.append({
                'invoice_id': invoice_id,
                'date': invoice['date'],
                'mobile': invoice['mobile'],
                'amount_due': invoice['total_due'],
                'game': invoice['game'],
                'station': invoice['station'],
                'controllers': invoice['controllers'],
                'base_cost': invoice['base_cost'],
                'food_cost': invoice['food_cost'],
                'wallet_used': invoice['wallet_used'],
                'loyalty_earned': invoice['loyalty_earned'],
                'remaining_wallet': invoice['remaining_wallet']
            })
            save_invoice_records(recs)
        except Exception:
            pass

        pdf_path = self._create_invoice_pdf(invoice_id, invoice)
        rel = os.path.relpath(pdf_path, BASE_DIR).replace(os.sep, '/')
        self._send_json({'invoice': invoice, 'pdf': '/' + rel})

def run_server(port=8000):
    os.chdir(BASE_DIR)
    server = ThreadingHTTPServer(('', port), POSHandler)
    print(f"Serving on port {port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()

if __name__ == '__main__':
    run_server(8000)
