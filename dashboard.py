# -*- coding: utf-8 -*-

import csv
import configparser
import hmac
import logging
import os
import secrets
import sqlite3
import subprocess
import sys
from datetime import datetime

from flask import (Flask, jsonify, redirect, render_template, request, session,
                   url_for)

# --- Konfiguracja ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [%(funcName)s] - %(message)s')
DB_FILE = os.path.join(BASE_DIR, 'printers.db')
CONFIG_FILE = os.path.join(BASE_DIR, 'config.ini')
PRINTERS_FILE = os.path.join(BASE_DIR, 'printers.csv')
LOCK_FILE = os.path.join(BASE_DIR, 'script.lock')
app = Flask(__name__)


# --- Autoryzacja (SEC-K3) ---
# Token pobierany z env DASH_AUTH_TOKEN lub [WWW] auth_token w config.ini.
# Bez skonfigurowanego tokenu dashboard zwraca 503 (fail-closed).

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


AUTH_TOKEN = load_auth_token()
app.secret_key = AUTH_TOKEN or 'prnt-mon-session-signing-fallback'


@app.before_request
def require_auth_and_csrf():
    if not AUTH_TOKEN:
        return ("Blad: brak tokenu autoryzacji. Ustaw DASH_AUTH_TOKEN (env) "
                "lub auth_token w sekcji [WWW] config.ini.", 503)
    if request.endpoint in ('login', 'static'):
        return None
    if not session.get('authenticated'):
        return redirect(url_for('login'))
    if request.method == 'POST':
        csrf = request.headers.get('X-CSRF-Token') or request.form.get('csrf_token')
        if not csrf or csrf != session.get('csrf_token'):
            return jsonify({'status': 'error', 'message': 'Nieprawidlowy token CSRF.'}), 403
    return None


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        token = (request.form.get('token') or '').strip()
        if AUTH_TOKEN and hmac.compare_digest(token, AUTH_TOKEN):
            session['authenticated'] = True
            session['csrf_token'] = secrets.token_hex(16)
            return redirect(url_for('index'))
        return render_template('login.html', error='Nieprawidlowy token.',
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
    """Wczytuje liste IP drukarek z pliku CSV, aby wyswietlic je wszystkie."""
    printers = []
    if not os.path.exists(PRINTERS_FILE):
        logging.error(f"Plik z drukarkami '{PRINTERS_FILE}' nie istnieje!")
        return []
    try:
        with open(PRINTERS_FILE, mode='r', encoding='utf-8') as infile:
            reader = csv.reader(infile)
            for row in reader:
                if row and row[0].strip():
                    printers.append(row[0].strip())
    except Exception as e:
        logging.error(f"Nie udalo sie wczytac pliku {PRINTERS_FILE}: {e}")
    return printers

def get_db_connection():
    """Nawiazuje polaczenie z baza danych SQLite."""
    try:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.OperationalError as e:
        logging.error(f"Nie mozna polaczyc z baza danych '{DB_FILE}': {e}")
        return None

def load_config():
    """Wczytuje konfiguracje z pliku config.ini."""
    config = configparser.ConfigParser()
    if not os.path.exists(CONFIG_FILE):
        logging.error(f"Plik konfiguracyjny {CONFIG_FILE} nie zostal znaleziony.")
        return None
    try:
        config.read(CONFIG_FILE, encoding='utf-8')
    except Exception as e:
        logging.error(f"Nie udalo sie odczytac pliku config.ini: {e}")
        return None
    return config

def get_toner_color(description):
    """Zwraca kolory dla paska postepu na podstawie opisu tonera."""
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
    """Uruchamia podane polecenie w tle w bezpieczny sposób (bez shell=True)."""
    logging.info(f"Otrzymano zadanie uruchomienia polecenia: {' '.join(command_list)}")
    try:
        with open(log_file, "a") as log:
            subprocess.Popen(command_list, stdout=log, stderr=subprocess.STDOUT)
        
        logging.info("Polecenie zostalo uruchomione w tle.")
        return True, "Zlecono zadanie. Wynik pojawi się po zakończeniu."
    except Exception as e:
        logging.error(f"Nie udało się uruchomić procesu: {e}")
        return False, f"Wystąpił błąd serwera: {e}"

# --- Głowne widoki aplikacji ---
# ZNAJDŹ I ZAKTUALIZUJ FUNKCJĘ index()
@app.route('/')
@app.route('/printer-monitor')
def index():
    """Glowny widok dashboardu, wyswietla wszystkie drukarki z CSV."""
    all_printer_ips = load_printers_from_csv()
    conn = get_db_connection()
    config = load_config()
    db_data = []
    last_run_time = "Nigdy" # Domyślna wartość

    if not config:
        return "Blad: Nie mozna zaladowac pliku konfiguracyjnego.", 500

    filter_keywords = [kw.strip().lower() for kw in config.get('MONITORING', 'toner_filter_keywords', fallback='').split(',')]
    exclude_keywords = [kw.strip().lower() for kw in config.get('MONITORING', 'toner_exclude_keywords', fallback='').split(',')]

    if conn:
        try:
            # Pobierz dane tonerów
            db_data = conn.execute('SELECT * FROM toner_status').fetchall()
            
            # Pobierz datę ostatniego uruchomienia
            last_run_cursor = conn.execute('SELECT run_timestamp FROM script_runs ORDER BY id DESC LIMIT 1')
            last_run_result = last_run_cursor.fetchone()
            if last_run_result:
                last_run_time = last_run_result['run_timestamp']
                
            conn.close()
        except sqlite3.OperationalError as e:
            logging.error(f"Blad zapytania do bazy danych: {e}.")
    
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
                'ip': ip, 'model': 'Brak danych', 'name': 'Oczekiwanie na dane...',
                'location': 'N/A', 'toners': [], 'last_updated': 'Nigdy'
            })
    
    try:
        final_printer_list.sort(key=lambda p: int(p['location']) if p['location'] and p['location'].isdigit() else 9999)
    except (ValueError, TypeError):
        logging.warning("Wystapil problem przy sortowaniu numerycznym lokalizacji.")
    
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # Przekaż nową zmienną do szablonu
    return render_template('index.html', printers=final_printer_list,
                           current_time=current_time, last_run_time=last_run_time,
                           csrf_token=session.get('csrf_token', ''))

@app.route('/run-report-counters', methods=['POST'])
def run_report_counters():
    """Uruchamia w tle skrypt generujacy raport licznikow, z mechanizmem blokady."""
    if os.path.exists(LOCK_FILE):
        return jsonify({'status': 'error', 'message': 'Inny proces jest już uruchomiony. Spróbuj ponownie za chwilę.'}), 409

    try:
        with open(LOCK_FILE, 'w') as f:
            f.write(str(datetime.now()))

        python_executable = sys.executable
        main_script_path = os.path.join(BASE_DIR, 'main.py')
        log_file = os.path.join(BASE_DIR, 'cron.log')
        command_list = [python_executable, main_script_path, '--report-counters', '--force-counters-email']
        
        success, message = run_background_script(command_list, log_file)
        if success:
            return jsonify({'status': 'success', 'message': 'Zlecono generowanie raportu. E-mail zostanie wysłany po zakończeniu.'})
        else:
            os.remove(LOCK_FILE)
            return jsonify({'status': 'error', 'message': message}), 500
    except Exception as e:
        logging.error(f"Blad podczas tworzenia blokady lub uruchamiania skryptu: {e}")
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
        return jsonify({'status': 'error', 'message': f"Wystąpił błąd serwera: {e}"}), 500

@app.route('/run-check-toner', methods=['POST'])
def run_check_toner():
    """Uruchamia w tle skrypt sprawdzajacy stan tonerow, z mechanizmem blokady."""
    if os.path.exists(LOCK_FILE):
        return jsonify({'status': 'error', 'message': 'Inny proces jest już uruchomiony. Spróbuj ponownie za chwilę.'}), 409

    try:
        with open(LOCK_FILE, 'w') as f:
            f.write(str(datetime.now()))

        python_executable = sys.executable
        main_script_path = os.path.join(BASE_DIR, 'main.py')
        log_file = os.path.join(BASE_DIR, 'cron.log')
        command_list = [python_executable, main_script_path, '--check-toner', '--force-toner-email']

        success, message = run_background_script(command_list, log_file)
        if success:
            return jsonify({'status': 'success', 'message': 'Zlecono aktualizację stanów tonerów. Odśwież stronę za chwilę.'})
        else:
            os.remove(LOCK_FILE)
            return jsonify({'status': 'error', 'message': message}), 500
    except Exception as e:
        logging.error(f"Blad podczas tworzenia blokady lub uruchamiania skryptu: {e}")
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
        return jsonify({'status': 'error', 'message': f"Wystąpił błąd serwera: {e}"}), 500

if __name__ == '__main__':
    if not AUTH_TOKEN:
        logging.critical("KRYTYCZNY BLAD: Brak tokenu autoryzacji (DASH_AUTH_TOKEN / [WWW] auth_token).")
    if not os.path.exists(DB_FILE):
        logging.critical(f"KRYTYCZNY BLAD: Plik bazy danych '{DB_FILE}' nie istnieje!")
        logging.critical("Uruchom najpierw skrypt 'main.py --check-toner', aby go utworzyc.")
    else:
        app.run(host='127.0.0.1', port=5001, debug=False)

