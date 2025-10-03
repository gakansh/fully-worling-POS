#!/usr/bin/env python3
"""
Simple gaming POS web application.

This module implements a lightweight HTTP server using Python's standard
library. It exposes a handful of JSON endpoints used by the front‑end
application. User accounts are persisted to a JSON file on disk, while
active sessions live in memory. When a session is terminated an invoice
is written as an HTML file and then converted to a PDF via a call to
LibreOffice running in headless mode.

The server provides the following routes:

  GET  /                 – serve the main HTML page
  GET  /static/...       – serve static assets (CSS/JS/images)
  GET  /invoices/...     – serve generated PDF invoices
  GET  /api/games        – return list of available games
  GET  /api/stations     – return current station occupancy
  GET  /api/users/<mobile>
                         – fetch or create a user record by mobile number
  POST /api/start_session
                         – begin a new gaming session
  POST /api/end_session  – end an existing session and compute invoice

The JSON body format for POST requests should be encoded in UTF‑8 and
contain the parameters documented in the respective handler functions.

Note: This server is deliberately simple and not hardened for a
production environment. It is designed to satisfy the requirements of
the assignment using only the Python standard library.
"""

import json
import os
import urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime, timezone
import uuid
import subprocess
from typing import Dict, Any
import html

# Absolute paths for data and output directories
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
STATIC_DIR = os.path.join(BASE_DIR, 'static')
INVOICE_DIR = os.path.join(BASE_DIR, 'invoices')

# Filenames for persistent storage
USERS_FILE = os.path.join(DATA_DIR, 'users.json')
GAMES_FILE = os.path.join(DATA_DIR, 'games.json')
SESSIONS_FILE = os.path.join(DATA_DIR, 'sessions.json')

# File to persist invoice/billing history. Each record will capture the invoice
# identifier, timestamp and key financial figures. This data is not exposed
# via the UI but kept for auditing and reporting purposes.
INVOICE_RECORDS_FILE = os.path.join(DATA_DIR, 'invoice_records.json')

# File for recording payment history. Each entry records the mobile number,
# the payment amount and a timestamp. This data isn't exposed through the UI;
# it's kept purely for bookkeeping.
PAYMENTS_FILE = os.path.join(DATA_DIR, 'payments.json')

# Initialise directories
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(INVOICE_DIR, exist_ok=True)

def load_users() -> Dict[str, Any]:
    """Load the users database from disk. Returns a dict keyed by mobile."""
    if not os.path.exists(USERS_FILE):
        return {}
    with open(USERS_FILE, 'r', encoding='utf-8') as f:
        try:
            data = json.load(f)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
    return {}

def load_payments() -> list:
    """Load the payment history from disk. Returns a list of payment records."""
    if not os.path.exists(PAYMENTS_FILE):
        return []
    try:
        with open(PAYMENTS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []

def save_payments(payments: list) -> None:
    """Persist the payment history to disk."""
    with open(PAYMENTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(payments, f, indent=2)

def save_users(users: Dict[str, Any]) -> None:
    """Persist the users database to disk."""
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(users, f, indent=2)

def load_games() -> Dict[str, Any]:
    """Load the games catalogue from disk. If missing, a default list is
    returned and written to disk for future edits."""
    # if not os.path.exists(GAMES_FILE):
    #     # Write default games file
    #     with open(GAMES_FILE, 'w', encoding='utf-8') as f:
    #         json.dump(default_games, f, indent=2)
    #     return default_games
    try:
        with open(GAMES_FILE, 'r', encoding='utf-8') as f:
            games = json.load(f)
            if isinstance(games, list):
                return games
    except json.JSONDecodeError:
        pass
    # fall back to default and overwrite corrupt file
    with open(GAMES_FILE, 'w', encoding='utf-8') as f:
        json.dump(default_games, f, indent=2)
    return default_games

# ---------------------------------------------------------------------------
# Invoice record helpers
#
# These helpers manage the persistence of the invoice history. Each time a
# session is ended and an invoice is generated, we append a record to the
# history. Records are stored in a simple JSON list within
# INVOICE_RECORDS_FILE. If the file doesn't exist or is corrupt, we start
# fresh with an empty list.

def load_invoice_records() -> list:
    """Load the invoice history from disk. Returns a list of record objects."""
    if not os.path.exists(INVOICE_RECORDS_FILE):
        return []
    try:
        with open(INVOICE_RECORDS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []

def save_invoice_records(records: list) -> None:
    """Persist the invoice history to disk."""
    with open(INVOICE_RECORDS_FILE, 'w', encoding='utf-8') as f:
        json.dump(records, f, indent=2)

# ---------------------------------------------------------------------------
# Session persistence helpers
#
# Sessions are normally stored only in memory. To persist active sessions across
# restarts, we load them from a JSON file at startup and write any changes
# back whenever sessions are created or terminated. Each session record
# matches the internal session representation used by POSHandler.

def load_sessions() -> Dict[str, Dict[str, Any]]:
    """Load active sessions from disk. Returns a dict keyed by session_id."""
    if not os.path.exists(SESSIONS_FILE):
        return {}
    try:
        with open(SESSIONS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}

def save_sessions(sessions: Dict[str, Dict[str, Any]]) -> None:
    """Persist the current active sessions to disk."""
    # Write out a copy rather than referencing the original to avoid accidental
    # modifications during serialization.
    with open(SESSIONS_FILE, 'w', encoding='utf-8') as f:
        json.dump(sessions, f, indent=2)


class POSHandler(SimpleHTTPRequestHandler):
    """
    HTTP request handler for the gaming POS.

    Extends SimpleHTTPRequestHandler to intercept API calls under the
    /api/ prefix. All other requests are delegated to the superclass,
    which serves static files relative to the BASE_DIR.
    """

    # Shared state across handler instances
    users = load_users()
    games = load_games()
    # Load any persisted sessions from disk so that active sessions survive
    # across server restarts. If the file is missing or corrupt the default
    # empty dict will be used.
    sessions: Dict[str, Dict[str, Any]] = load_sessions()

    def _send_json(self, data: Any, status: int = 200) -> None:
        """Helper to send a JSON response."""
        encoded = json.dumps(data).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _read_request_json(self) -> Any:
        """Read and parse JSON body from a POST request."""
        length = int(self.headers.get('Content-Length', '0'))
        body = self.rfile.read(length) if length > 0 else b''
        try:
            return json.loads(body.decode('utf-8'))
        except Exception:
            return None

    def do_GET(self) -> None:
        """Handle GET requests. Routes starting with /api/ are treated as API calls."""
        parsed_path = urllib.parse.urlparse(self.path)
        path = parsed_path.path
        if path.startswith('/api/'):
            if path == '/api/games':
                self._handle_get_games()
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
            # Unknown API
            self._send_json({'error': 'Unknown API endpoint'}, status=404)
            return
        # For root path serve index.html explicitly so the directory listing isn't shown
        if path == '/':
            self.path = '/index.html'
        # Let SimpleHTTPRequestHandler serve the file relative to BASE_DIR
        return SimpleHTTPRequestHandler.do_GET(self)

    def do_POST(self) -> None:
        """Handle POST requests for starting and ending sessions."""
        parsed_path = urllib.parse.urlparse(self.path)
        path = parsed_path.path
        if path == '/api/start_session':
            self._handle_start_session()
            return
        if path == '/api/end_session':
            self._handle_end_session()
            return
        # Unknown API
        self._send_json({'error': 'Unknown API endpoint'}, status=404)

    def _handle_get_games(self) -> None:
        """Return the list of available games."""
        self._send_json(POSHandler.games)

    def _handle_get_stations(self) -> None:
        """Return a list of stations A‑G and their occupancy status."""
        stations = {}
        # Mark each station A..G as free by default
        for letter in ['A', 'B', 'C', 'D', 'E', 'F', 'G']:
            stations[letter] = {'occupied': False, 'session_id': None}
        for sid, sess in POSHandler.sessions.items():
            stations[sess['station']] = {'occupied': True, 'session_id': sid}
        self._send_json(stations)

    def _handle_get_sessions(self) -> None:
        """Return a list of active sessions with details."""
        # convert sessions dict to list for the client
        sessions_list = []
        for sid, sess in POSHandler.sessions.items():
            sessions_list.append(sess)
        self._send_json(sessions_list)

    def _handle_get_user(self, mobile: str) -> None:
        """Fetch an existing user or create a new one if absent.

        A user record looks like {"mobile": "123", "wallet": 0}.
        """
        mobile = mobile.strip()
        if not mobile:
            self._send_json({'error': 'Mobile number required'}, status=400)
            return
        user = POSHandler.users.get(mobile)
        if user is None:
            # create new user
            user = {'mobile': mobile, 'wallet': 0}
            POSHandler.users[mobile] = user
            save_users(POSHandler.users)
        self._send_json(user)

    def _handle_start_session(self) -> None:
        """Start a new gaming session.

        Expected JSON body:
        {
          "mobile": "123",       # existing or new user
          "station": "A",        # letter A‑G
          "game": "Forza Horizon 5",
          "controllers": 2         # optional, ignored for forza
        }
        """
        payload = self._read_request_json()
        if not isinstance(payload, dict):
            self._send_json({'error': 'Invalid JSON payload'}, status=400)
            return
        mobile = str(payload.get('mobile', '')).strip()
        station = str(payload.get('station', '')).strip().upper()
        game_name = str(payload.get('game', '')).strip()
        controllers = int(payload.get('controllers', 0))
        if not mobile or station not in ['A', 'B', 'C', 'D', 'E', 'F', 'G'] or not game_name:
            self._send_json({'error': 'Missing or invalid fields'}, status=400)
            return
        # ensure user exists
        user = POSHandler.users.get(mobile)
        if user is None:
            user = {'mobile': mobile, 'wallet': 0}
            POSHandler.users[mobile] = user
            save_users(POSHandler.users)
        # check station availability
        for sess_id, sess in POSHandler.sessions.items():
            if sess['station'] == station:
                self._send_json({'error': f'Station {station} is already occupied'}, status=409)
                return
        # fetch game object to validate controllers
        game_obj = next((g for g in POSHandler.games if g['name'] == game_name), None)
        if not game_obj:
            self._send_json({'error': 'Unknown game selected'}, status=400)
            return
        if not game_obj.get('requires_controllers', True):
            controllers = 0
        # create session
        sid = str(uuid.uuid4())
        POSHandler.sessions[sid] = {
            'session_id': sid,
            'mobile': mobile,
            'station': station,
            'game': game_name,
            'controllers': controllers,
            'start_time': datetime.now(timezone.utc).isoformat()
        }
        self._send_json({'session_id': sid, 'status': 'started'})

        # Persist the new session to disk so that it survives a restart.
        try:
            save_sessions(POSHandler.sessions)
        except Exception:
            pass

    def _calculate_duration_hours(self, start_iso: str, end_dt: datetime) -> float:
        """Compute session duration in hours with rounding rules.

        Any remainder over 15 minutes rounds up to the next half hour.
        For example, 1h05m -> 1.0, 1h20m -> 1.5.
        """
        try:
            start_dt = datetime.fromisoformat(start_iso)
        except ValueError:
            # fallback: treat as now
            start_dt = end_dt
        diff = end_dt - start_dt
        total_minutes = diff.total_seconds() / 60.0
        if total_minutes < 0:
            total_minutes = 0
        hours = int(total_minutes // 60)
        remainder = total_minutes - hours * 60
        # Round up to half hour if remainder > 15 minutes
        extra = 0
        if remainder > 15:
            extra = 0.5
        return hours + extra

    def _create_invoice_pdf(self, invoice_id: str, invoice_data: Dict[str, Any]) -> str:
        """
        Generate an HTML invoice and convert to PDF using LibreOffice (headless).
        Returns the absolute path to the resulting PDF if conversion succeeds,
        otherwise returns the HTML path as a fallback.
        """
        # Ensure output directory exists
        os.makedirs(INVOICE_DIR, exist_ok=True)

        # File paths
        html_path = os.path.join(INVOICE_DIR, f"{invoice_id}.html")
        pdf_path  = os.path.join(INVOICE_DIR, f"{invoice_id}.pdf")

        # Helper to safely format currency and escape text
        def money(v) -> str:
            try:
                return f"₹{float(v):.2f}"
            except Exception:
                return str(v)

        def esc(v) -> str:
            return html.escape(str(v))  # requires: import html

        # Build minimal, printer-friendly HTML (good for thermal printers too)
        created_at = invoice_data.get("date", "")
        rows = [
            ("Invoice ID",        invoice_id),
            ("Date",              created_at),
            ("Mobile",            invoice_data.get("mobile", "")),
            ("Station",           invoice_data.get("station", "")),
            ("Game",              invoice_data.get("game", "")),
            ("Controllers",       invoice_data.get("controllers", 0)),
            ("Duration (hrs)",    f"{float(invoice_data.get('duration_hours', 0)):.2f}"),
            ("Base Cost",         money(invoice_data.get("base_cost", 0))),
            ("Food Cost",         money(invoice_data.get("food_cost", 0))),
            ("Wallet Used",       money(invoice_data.get("wallet_used", 0))),
            ("Total Due",         money(invoice_data.get("total_due", 0))),
            ("Loyalty Earned",    money(invoice_data.get("loyalty_earned", 0))),
            ("Remaining Wallet",  money(invoice_data.get("remaining_wallet", 0))),
        ]

        table_rows_html = "\n".join(
            f"<tr><th>{esc(k)}</th><td>{esc(v)}</td></tr>" for k, v in rows
        )

        html_doc = f"""<!doctype html>
    <html>
    <head>
    <meta charset="utf-8">
    <title>Invoice {esc(invoice_id)}</title>
    <style>
    :root {{
        --fg:#111; --muted:#666; --line:#ddd;
    }}
    * {{ box-sizing:border-box; }}
    body {{
        font-family: -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica, Arial, "Noto Sans", sans-serif;
        color: var(--fg); margin: 0; padding: 24px;
    }}
    .wrap {{ max-width: 640px; margin: 0 auto; }}
    .brand {{ text-align:center; margin-bottom: 8px; font-size: 22px; font-weight: 700; letter-spacing: .3px; }}
    .sub   {{ text-align:center; color: var(--muted); margin-bottom: 18px; font-size: 12px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ text-align: left; padding: 8px 10px; vertical-align: top; }}
    th {{ width: 45%; font-weight: 600; color: #222; background: #f6f6f6; }}
    tr + tr th, tr + tr td {{ border-top: 1px solid var(--line); }}
    .total th, .total td {{ border-top: 2px solid #000; font-weight: 700; }}
    .footer {{ margin-top: 16px; text-align:center; color: var(--muted); font-size: 12px; }}
    @media print {{
        body {{ padding: 0; }}
        .wrap {{ max-width: 100%; margin: 0; padding: 0; }}
    }}
    </style>
    </head>
    <body>
    <div class="wrap">
        <div class="brand">Gaming POS Invoice</div>
        <div class="sub">{esc(created_at)}</div>
        <table>
        {table_rows_html}
        </table>
        <div class="footer">Thank you for visiting! Enjoy your game.</div>
    </div>
    </body>
    </html>"""

        # Write HTML file
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_doc)

        # Convert to PDF using LibreOffice if available
        try:
            # Call LibreOffice headless conversion
            # On macOS, soffice may be available via /Applications or PATH; we rely on PATH here.
            subprocess.run(
                [
                    "soffice",
                    "--headless",
                    "--convert-to", "pdf",
                    "--outdir", INVOICE_DIR,
                    html_path,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )
            # If conversion succeeded and file exists, return PDF
            if os.path.exists(pdf_path):
                return pdf_path
        except Exception:
            # Swallow conversion errors and fall back to HTML
            pass

        # Fallback: return HTML if PDF couldn't be created
        return html_path

    def _handle_end_session(self) -> None:
        """End an existing session and compute the final invoice.

        Expected JSON body:
        {
          "session_id": "...",
          "food_cost": 50.0,
          "use_wallet": true
        }
        """
        payload = self._read_request_json()
        if not isinstance(payload, dict):
            self._send_json({'error': 'Invalid JSON payload'}, status=400)
            return
        session_id = payload.get('session_id')
        food_cost = float(payload.get('food_cost', 0) or 0)
        use_wallet = bool(payload.get('use_wallet', True))
        if not session_id or session_id not in POSHandler.sessions:
            self._send_json({'error': 'Invalid session id'}, status=400)
            return
        sess = POSHandler.sessions.pop(session_id)
        # Persist session removal
        try:
            save_sessions(POSHandler.sessions)
        except Exception:
            pass
        end_time = datetime.now(timezone.utc)
        # Calculate duration
        duration_hours = self._calculate_duration_hours(sess['start_time'], end_time)
        # Determine game pricing
        game_obj = next((g for g in POSHandler.games if g['name'] == sess['game']), None)
        if not game_obj:
            game_price_per_hour = 100
        else:
            game_price_per_hour = game_obj['price_per_hour']
        # compute base cost
        if game_obj and not game_obj.get('requires_controllers', True):
            # for forza or games without controllers: flat rate per hour
            base_cost = duration_hours * game_price_per_hour
        else:
            # other games: cost per controller per hour
            base_cost = duration_hours * game_price_per_hour * max(1, sess.get('controllers', 1))
        # wallet management
        user = POSHandler.users.get(sess['mobile'], {'mobile': sess['mobile'], 'wallet': 0})
        wallet_available = float(user.get('wallet', 0))
        wallet_used = 0.0
        total_due_before_wallet = base_cost + food_cost
        if use_wallet and wallet_available > 0:
            wallet_used = min(wallet_available, total_due_before_wallet)
        remaining_due = total_due_before_wallet - wallet_used
        # loyalty points: 10% of total bill (base + food) before wallet usage
        loyalty_earned = 0.10 * total_due_before_wallet
        # update user's wallet: subtract used, add earned
        new_wallet_balance = wallet_available - wallet_used + loyalty_earned
        user['wallet'] = round(new_wallet_balance, 2)
        POSHandler.users[user['mobile']] = user
        save_users(POSHandler.users)

        # Record the payment for bookkeeping. We store each payment as a simple
        # object with the mobile number, the amount paid (after wallet usage) and
        # the date. This history is not exposed through the UI but persists to
        # a JSON file for later audit.
        try:
            payments = load_payments()
            payments.append({
                'mobile': sess['mobile'],
                'amount': remaining_due,
                'date': end_time.astimezone().strftime('%Y-%m-%d %H:%M:%S')
            })
            save_payments(payments)
        except Exception:
            # If recording fails, we silently ignore to avoid breaking billing
            pass
        # prepare invoice data
        invoice_id = session_id.replace('-', '')
        invoice_data = {
            'date': end_time.astimezone().strftime('%Y-%m-%d %H:%M:%S'),
            'mobile': sess['mobile'],
            'station': sess['station'],
            'game': sess['game'],
            'controllers': sess.get('controllers', 0),
            'duration_hours': duration_hours,
            'base_cost': base_cost,
            'food_cost': food_cost,
            'wallet_used': wallet_used,
            'total_due': remaining_due,
            'loyalty_earned': loyalty_earned,
            'remaining_wallet': user['wallet']
        }

        # Save invoice record for auditing. We include the invoice id, date and
        # the final amount due along with other relevant fields. This record
        # persists outside of the UI and can be used for reporting later.
        try:
            records = load_invoice_records()
            record = {
                'invoice_id': invoice_id,
                'date': invoice_data['date'],
                'mobile': invoice_data['mobile'],
                'amount_due': invoice_data['total_due'],
                'game': invoice_data['game'],
                'station': invoice_data['station'],
                'controllers': invoice_data['controllers'],
                'base_cost': invoice_data['base_cost'],
                'food_cost': invoice_data['food_cost'],
                'wallet_used': invoice_data['wallet_used'],
                'loyalty_earned': invoice_data['loyalty_earned'],
                'remaining_wallet': invoice_data['remaining_wallet']
            }
            records.append(record)
            save_invoice_records(records)
        except Exception:
            # In case of any failure while saving the record, proceed without
            # interrupting the billing flow.
            pass
        # generate invoice PDF
        pdf_path = self._create_invoice_pdf(invoice_id, invoice_data)
        # Build response: relative URL to invoice
        rel_path = os.path.relpath(pdf_path, BASE_DIR)
        self._send_json({
            'invoice_id': invoice_id,
            'invoice': invoice_data,
            'pdf': '/' + rel_path.replace(os.sep, '/')
        })


def run_server(port: int = 8000) -> None:
    """Launch the HTTP server on the specified port."""
    os.chdir(BASE_DIR)
    server_address = ('', port)
    httpd = ThreadingHTTPServer(server_address, POSHandler)
    print(f"Serving on port {port}...")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("Shutting down server...")
        httpd.server_close()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Run the Gaming POS server')
    parser.add_argument('--port', type=int, default=8000, help='Port number to listen on')
    args = parser.parse_args()
    run_server(args.port)