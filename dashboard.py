# -*- coding: utf-8 -*-

import csv
import configparser
import hmac
import logging
import logging.handlers
import os
import secrets
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta

from flask import (Flask, jsonify, redirect, render_template, request, session,
                   url_for)

import lockfile

# --- Konfiguracja ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, 'printers.db')
CONFIG_FILE = os.path.join(BASE_DIR, 'config.ini')
PRINTERS_FILE = os.path.join(BASE_DIR, 'printers.csv')
LOCK_FILE = os.path.join(BASE_DIR, 'script.lock')
app = Flask(__name__)


def setup_logging():
    """Console logging + rotating file (SHOULD: log rotation)."""
    fmt = '%(asctime)s - %(levelname)s - [%(funcName)s] - %(message)s'
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if root.handlers:
        for handler in root.handlers:
            handler.setFormatter(logging.Formatter(fmt))
        return
    stream = logging.StreamHandler()
    stream.setFormatter(logging.Formatter(fmt))
    root.addHandler(stream)
    try:
        rotating = logging.handlers.RotatingFileHandler(
            os.path.join(BASE_DIR, 'printer_monitor.log'),
            maxBytes=1024 * 1024, backupCount=3, encoding='utf-8')
        rotating.setFormatter(logging.Formatter(fmt))
        root.addHandler(rotating)
    except OSError:
        pass


setup_logging()


# --- Authentication (SEC-K3) ---
# Token read from env DASH_AUTH_TOKEN or [WWW] auth_token in config.ini.
# Without a configured token the dashboard returns 503 (fail-closed).
#
# AUTO_LOGIN mode ([WWW] auto_login = true / env DASH_AUTO_LOGIN=true):
# authentication happens automatically (no token prompt) - allowed
# ONLY when the dashboard is available locally (docker -p 127.0.0.1:5001:5001).
# CSRF on POST stays active in both modes.

def load_auth_token():
    token = os.environ.get('DASH_AUTH_TOKEN')
    if token:
        return token.strip()
    parser = configparser.ConfigParser()
    try:
        parser.read(CONFIG_FILE, encoding='utf-8')
        if parser.has_option('WWW', 'auth_token'):
            return parser.get('WWW', 'auth_token').strip()
    except Exception:
        pass
    return ''


def load_auto_login():
    env = os.environ.get('DASH_AUTO_LOGIN', '')
    if env:
        return env.strip().lower() in ('1', 'true', 'yes', 'on')
    parser = configparser.ConfigParser()
    try:
        parser.read(CONFIG_FILE, encoding='utf-8')
        if parser.has_option('WWW', 'auto_login'):
            return parser.getboolean('WWW', 'auto_login')
    except Exception:
        pass
    return False


AUTH_TOKEN = load_auth_token()
AUTO_LOGIN = load_auto_login()
app.secret_key = AUTH_TOKEN or 'prnt-mon-session-signing-fallback'
app.permanent_session_lifetime = timedelta(days=30)


@app.before_request
def require_auth_and_csrf():
    session.permanent = True  # 30-day cookie session - token rarely needed
    if AUTO_LOGIN:
        if not session.get('authenticated'):
            session['authenticated'] = True
            session['csrf_token'] = secrets.token_hex(16)
    elif not AUTH_TOKEN:
        return ("Error: missing auth token. Set DASH_AUTH_TOKEN (env) "
                "or auth_token in the [WWW] section of config.ini.", 503)
    elif not session.get('authenticated'):
        if request.endpoint in ('login', 'static'):
            return None
        return redirect(url_for('login'))
    if request.endpoint in ('login', 'static'):
        return None
    if request.method == 'POST':
        csrf = request.headers.get('X-CSRF-Token') or request.form.get('csrf_token')
        if not csrf or csrf != session.get('csrf_token'):
            return jsonify({'status': 'error', 'message': 'Invalid CSRF token.'}), 403
    return None


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        token = (request.form.get('token') or '').strip()
        if AUTH_TOKEN and hmac.compare_digest(token, AUTH_TOKEN):
            session['authenticated'] = True
            session['csrf_token'] = secrets.token_hex(16)
            return redirect(url_for('index'))
        return render_template('login.html', error='Invalid token.',
                               csrf_token=session.get('csrf_token', '')), 401
    if session.get('authenticated'):
        return redirect(url_for('index'))
    session['csrf_token'] = session.get('csrf_token') or secrets.token_hex(16)
    return render_template('login.html', error=None, csrf_token=session['csrf_token'])


@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect(url_for('login'))

# --- Funkcje pomocnicze ---
def load_printers_from_csv():
    """Load the list of printer IPs from the CSV file to display them all."""
    printers = []
    if not os.path.exists(PRINTERS_FILE):
        logging.error(f"Printers file '{PRINTERS_FILE}' does not exist!")
        return []
    try:
        with open(PRINTERS_FILE, mode='r', encoding='utf-8') as infile:
            reader = csv.reader(infile)
            for row in reader:
                if row and row[0].strip() and not row[0].strip().startswith('#'):
                    printers.append(row[0].strip())
    except Exception as e:
        logging.error(f"Failed to read file {PRINTERS_FILE}: {e}")
    return printers

def get_db_connection():
    """Open a connection to the SQLite database."""
    try:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.OperationalError as e:
        logging.error(f"Cannot connect to database '{DB_FILE}': {e}")
        return None

def load_config():
    """Load configuration from config.ini."""
    config = configparser.ConfigParser()
    if not os.path.exists(CONFIG_FILE):
        logging.error(f"Configuration file {CONFIG_FILE} was not found.")
        return None
    try:
        config.read(CONFIG_FILE, encoding='utf-8')
    except Exception as e:
        logging.error(f"Failed to read config.ini: {e}")
        return None
    return config

def get_toner_color(description):
    """Return progress bar colors based on the toner description."""
    desc_lower = description.lower()
    if 'black' in desc_lower or 'czarny' in desc_lower:
        return {'bg': '#343a40', 'text': '#ffffff'}
    if 'cyan' in desc_lower:
        return {'bg': '#00aef0', 'text': '#ffffff'}
    if 'magenta' in desc_lower:
        return {'bg': '#ec008c', 'text': '#ffffff'}
    if 'yellow' in desc_lower:
        return {'bg': '#fff200', 'text': '#000000'}
    return {'bg': '#6c757d', 'text': '#ffffff'}

def run_background_script(command_list, log_file):
    """Run the given command in the background safely (no shell=True)."""
    logging.info(f"Received task to run command: {' '.join(command_list)}")
    try:
        with open(log_file, "a") as log:
            subprocess.Popen(command_list, stdout=log, stderr=subprocess.STDOUT)
        
        logging.info("Command started in the background.")
        return True, "Task submitted. The result will appear when it finishes."
    except Exception as e:
        logging.error(f"Failed to start the process: {e}")
        return False, f"Server error: {e}"

# --- Main application views ---
# FIND AND UPDATE THE index() FUNCTION
@app.route('/')
@app.route('/printer-monitor')
def index():
    """Main dashboard view - displays all printers from the CSV."""
    all_printer_ips = load_printers_from_csv()
    conn = get_db_connection()
    config = load_config()
    db_data = []
    last_run_time = "Never" # Default value

    if not config:
        return "Error: could not load the configuration file.", 500

    filter_keywords = [kw.strip().lower() for kw in config.get('MONITORING', 'toner_filter_keywords', fallback='').split(',')]
    exclude_keywords = [kw.strip().lower() for kw in config.get('MONITORING', 'toner_exclude_keywords', fallback='').split(',')]

    if conn:
        try:
            # Fetch toner data
            db_data = conn.execute('SELECT * FROM toner_status').fetchall()
            
            # Fetch the last run timestamp
            last_run_cursor = conn.execute('SELECT run_timestamp FROM script_runs ORDER BY id DESC LIMIT 1')
            last_run_result = last_run_cursor.fetchone()
            if last_run_result:
                last_run_time = last_run_result['run_timestamp']
                
            conn.close()
        except sqlite3.OperationalError as e:
            logging.error(f"Database query error: {e}.")
    
    # ... (reszta funkcji bez zmian)
    db_printers = {}
    for row in db_data:
        ip = row['ip_address']
        if ip not in db_printers:
            db_printers[ip] = {
                'ip': ip, 'model': row['model'], 'name': row['device_name'],
                'location': row['location'], 'toners': [], 'last_updated': row['last_updated']
            }
        
        toner_desc_lower = row['toner_desc'].lower()
        if filter_keywords and not any(kw in toner_desc_lower for kw in filter_keywords): continue
        if exclude_keywords and any(kw in toner_desc_lower for kw in exclude_keywords): continue
        
        colors = get_toner_color(row['toner_desc'])
        db_printers[ip]['toners'].append({
            'desc': row['toner_desc'], 'level': row['toner_level'],
            'bg_color': colors['bg'], 'text_color': colors['text']
        })

    final_printer_list = []
    for ip in all_printer_ips:
        if ip in db_printers and db_printers[ip]['toners']:
            final_printer_list.append(db_printers[ip])
        else:
            final_printer_list.append({
                'ip': ip, 'model': 'No data', 'name': 'Waiting for data...',
                'location': 'N/A', 'toners': [], 'last_updated': 'Nigdy'
            })
    
    try:
        final_printer_list.sort(key=lambda p: int(p['location']) if p['location'] and p['location'].isdigit() else 9999)
    except (ValueError, TypeError):
        logging.warning("Problem sorting locations numerically.")
    
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # Pass the new variable to the template
    return render_template('index.html', printers=final_printer_list,
                           current_time=current_time, last_run_time=last_run_time,
                           csrf_token=session.get('csrf_token', ''))

@app.route('/run-report-counters', methods=['POST'])
def run_report_counters():
    """Run the counter report script in the background, with a lock mechanism."""
    if lockfile.is_locked(LOCK_FILE, max_age_seconds=3600):
        return jsonify({'status': 'error', 'message': 'Another process is already running. Try again in a moment.'}), 409

    try:
        python_executable = sys.executable
        main_script_path = os.path.join(BASE_DIR, 'main.py')
        log_file = os.path.join(BASE_DIR, 'cron.log')
        command_list = [python_executable, main_script_path, '--report-counters', '--force-counters-email']
        
        success, message = run_background_script(command_list, log_file)
        if success:
            return jsonify({'status': 'success', 'message': 'Report generation scheduled. The e-mail will be sent when it finishes.'})
        return jsonify({'status': 'error', 'message': message}), 500
    except Exception as e:
        logging.error(f"Error while starting the script: {e}")
        return jsonify({'status': 'error', 'message': f"Server error: {e}"}), 500

@app.route('/run-check-toner', methods=['POST'])
def run_check_toner():
    """Run the toner check script in the background, with a lock mechanism."""
    if lockfile.is_locked(LOCK_FILE, max_age_seconds=3600):
        return jsonify({'status': 'error', 'message': 'Another process is already running. Try again in a moment.'}), 409

    try:
        python_executable = sys.executable
        main_script_path = os.path.join(BASE_DIR, 'main.py')
        log_file = os.path.join(BASE_DIR, 'cron.log')
        command_list = [python_executable, main_script_path, '--check-toner', '--force-toner-email']

        success, message = run_background_script(command_list, log_file)
        if success:
            return jsonify({'status': 'success', 'message': 'Toner update scheduled. Refresh the page in a moment.'})
        return jsonify({'status': 'error', 'message': message}), 500
    except Exception as e:
        logging.error(f"Error while starting the script: {e}")
        return jsonify({'status': 'error', 'message': f"Server error: {e}"}), 500

if __name__ == '__main__':
    if not AUTH_TOKEN:
        logging.critical("CRITICAL ERROR: no auth token (DASH_AUTH_TOKEN / [WWW] auth_token).")
    if not os.path.exists(DB_FILE):
        logging.critical(f"CRITICAL ERROR: database file '{DB_FILE}' does not exist!")
        logging.critical("Run 'main.py --check-toner' first to create it.")
    else:
        app.run(host='127.0.0.1', port=5001, debug=False)


