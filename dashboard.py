# -*- coding: utf-8 -*-

import sqlite3
from flask import Flask, render_template, jsonify
import logging
from datetime import datetime
import os
import configparser
import subprocess
import csv

# --- Konfiguracja ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [%(funcName)s] - %(message)s')
DB_FILE = os.path.join(BASE_DIR, 'printers.db')
CONFIG_FILE = os.path.join(BASE_DIR, 'config.ini')
PRINTERS_FILE = os.path.join(BASE_DIR, 'printers.csv')
app = Flask(__name__)

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

def run_background_script(command, log_file):
    """Uruchamia podane polecenie w tle i loguje jego wyjscie."""
    logging.info(f"Otrzymano zadanie uruchomienia polecenia: {command}")
    try:
        with open(log_file, "a") as log:
            subprocess.Popen(command, shell=True, stdout=log, stderr=subprocess.STDOUT)
        
        logging.info("Polecenie zostalo uruchomione w tle.")
        return True, "Zlecono zadanie. Wynik pojawi sie po zakonczeniu."
    except Exception as e:
        logging.error(f"Nie udalo sie uruchomic procesu: {e}")
        return False, f"Wystapil blad serwera: {e}"

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
    return render_template('index.html', printers=final_printer_list, current_time=current_time, last_run_time=last_run_time)

@app.route('/run-report-counters', methods=['POST'])
def run_report_counters():
    command = "/home/admin/printer-monitor/venv/bin/python3 /home/admin/printer-monitor/main.py --report-counters --force-counters-email"
    log_file = "/home/admin/printer-monitor/cron.log"
    success, message = run_background_script(command, log_file)
    if success:
        return jsonify({'status': 'success', 'message': 'Zlecono generowanie raportu. E-mail zostanie wyslany po zakonczeniu.'})
    else:
        return jsonify({'status': 'error', 'message': message}), 500
        
@app.route('/run-check-toner', methods=['POST'])
def run_check_toner():
    command = "/home/admin/printer-monitor/venv/bin/python3 /home/admin/printer-monitor/main.py --check-toner --force-toner-email"
    log_file = "/home/admin/printer-monitor/cron.log"
    success, message = run_background_script(command, log_file)
    if success:
        return jsonify({'status': 'success', 'message': 'Zlecono aktualizacje stanow tonerow. Odswiez strone za chwile.'})
    else:
        return jsonify({'status': 'error', 'message': message}), 500

if __name__ == '__main__':
    if not os.path.exists(DB_FILE):
        logging.critical(f"KRYTYCZNY BLAD: Plik bazy danych '{DB_FILE}' nie istnieje!")
        logging.critical("Uruchom najpierw skrypt 'main.py --check-toner', aby go utworzyc.")
    else:
        app.run(host='0.0.0.0', port=5001, debug=True)

