# -*- coding: utf-8 -*-

import csv
import argparse
import configparser
import html
import ipaddress
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
import logging
import logging.handlers
import asyncio
import socket
import sys
import os
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from cryptography.fernet import Fernet
import sqlite3

import lockfile

# Komponenty do web scrapingu
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import WebDriverException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup

# Import dla raportow Excel
try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

# Komponenty do SNMP
from pysnmp.hlapi.asyncio import (
    SnmpEngine, CommunityData, UdpTransportTarget,
    ContextData, ObjectType, ObjectIdentity, get_cmd, next_cmd
)

# --- Konfiguracja ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, 'config.ini')
PRINTERS_FILE = os.path.join(BASE_DIR, 'printers.csv')
PRINTERS_COUNTERS_FILE = os.path.join(BASE_DIR, 'printers_counters.csv')
DB_FILE = os.path.join(BASE_DIR, 'printers.db')
LOCK_FILE = os.path.join(BASE_DIR, 'script.lock')
WEB_WORKERS_DEFAULT = 3


def setup_logging():
    """Logowanie do konsoli + rotujacy plik (SHOULD: rotacja logow)."""
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
    config = load_config()
    log_file = 'printer_monitor.log'
    if config and config.has_option('MONITORING', 'log_file'):
        log_file = config.get('MONITORING', 'log_file')
    try:
        rotating = logging.handlers.RotatingFileHandler(
            os.path.join(BASE_DIR, log_file), maxBytes=1024 * 1024, backupCount=3,
            encoding='utf-8')
        rotating.setFormatter(logging.Formatter(fmt))
        root.addHandler(rotating)
    except OSError:
        pass


# --- Funkcje Bazy Danych ---
def init_db():
    """Inicjalizuje baze danych i tworzy/aktualizuje tabele."""
    try:
        con = sqlite3.connect(DB_FILE)
        cur = con.cursor()
        
        cur.execute('''
            CREATE TABLE IF NOT EXISTS toner_status (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ip_address TEXT NOT NULL,
                model TEXT,
                device_name TEXT,
                location TEXT,
                toner_desc TEXT NOT NULL,
                toner_level REAL,
                last_updated TEXT,
                alert_sent_timestamp TEXT,
                UNIQUE(ip_address, toner_desc)
            )
        ''')
        
        cur.execute('''
            CREATE TABLE IF NOT EXISTS counter_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ip_address TEXT NOT NULL,
                model TEXT,
                device_name TEXT,
                location TEXT,
                report_date TEXT NOT NULL,
                color_count INTEGER,
                bw_count INTEGER,
                total_count INTEGER,
                UNIQUE(ip_address, report_date)
            )
        ''')

        cur.execute('''
            CREATE TABLE IF NOT EXISTS script_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_type TEXT,
                run_timestamp TEXT
            )
        ''')
        
        try:
            cur.execute('ALTER TABLE toner_status ADD COLUMN alert_sent_timestamp TEXT')
        except sqlite3.OperationalError:
            pass 

        con.commit()
        con.close()
        logging.info(f"Baza danych '{DB_FILE}' zostala zainicjalizowana/zaktualizowana.")
    except Exception as e:
        logging.error(f"Nie udalo sie zainicjalizowac bazy danych: {e}")

def log_script_run(run_type):
    """Zapisuje znacznik czasu ostatniego uruchomienia skryptu."""
    try:
        con = sqlite3.connect(DB_FILE)
        cur = con.cursor()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur.execute('INSERT INTO script_runs (run_type, run_timestamp) VALUES (?, ?)', (run_type, now))
        con.commit()
        con.close()
        logging.info(f"Zanotowano uruchomienie skryptu: {run_type} o {now}")
    except Exception as e:
        logging.error(f"Nie udalo sie zapisac informacji o uruchomieniu skryptu: {e}")

def update_toner_status_in_db(toner_data):
    """Zapisuje lub aktualizuje status tonera w bazie danych."""
    try:
        con = sqlite3.connect(DB_FILE)
        cur = con.cursor()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        for toner in toner_data:
            cur.execute('''
                INSERT INTO toner_status (ip_address, model, device_name, location, toner_desc, toner_level, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ip_address, toner_desc) DO UPDATE SET
                model=excluded.model,
                device_name=excluded.device_name,
                location=excluded.location,
                toner_level=excluded.toner_level,
                last_updated=excluded.last_updated
            ''', (
                toner.get('ip'), toner.get('model'), toner.get('name'), toner.get('location'),
                toner.get('desc'), toner.get('level'), now
            ))
        con.commit()
        con.close()
        logging.info(f"Zaktualizowano {len(toner_data)} wpisow o tonerach w bazie danych.")
    except Exception as e:
        logging.error(f"Nie udalo sie zaktualizowac danych w bazie: {e}")

def update_alert_timestamp(alerts):
    """Aktualizuje znacznik czasu wyslania alertu dla podanych tonerow."""
    try:
        con = sqlite3.connect(DB_FILE)
        cur = con.cursor()
        now = datetime.now().isoformat()
        for alert in alerts:
            cur.execute('''
                UPDATE toner_status SET alert_sent_timestamp = ? WHERE ip_address = ? AND toner_desc = ?
            ''', (now, alert.get('ip'), alert.get('desc')))
        con.commit()
        con.close()
        logging.info(f"Zaktualizowano znaczniki czasu wyslania alertu dla {len(alerts)} tonerow.")
    except Exception as e:
        logging.error(f"Nie udalo sie zaktualizowac znacznikow czasu alertow w bazie: {e}")

def get_last_alert_timestamp(ip, desc):
    """Pobiera date ostatniego alertu dla danego tonera."""
    try:
        con = sqlite3.connect(DB_FILE)
        cur = con.cursor()
        cur.execute('SELECT alert_sent_timestamp FROM toner_status WHERE ip_address = ? AND toner_desc = ?', (ip, desc))
        result = cur.fetchone()
        con.close()
        if result and result[0]:
            return datetime.fromisoformat(result[0])
    except Exception as e:
        logging.error(f"Blad odczytu znacznika czasu alertu z bazy: {e}")
    return None

def save_counter_history(counters_data):
    """Zapisuje historie licznikow do bazy danych."""
    try:
        con = sqlite3.connect(DB_FILE)
        cur = con.cursor()
        today_str = datetime.now().strftime("%Y-%m-%d")
        
        for data in counters_data:
            if data.get('status') == 'OK':
                cur.execute('''
                    INSERT INTO counter_history (ip_address, model, device_name, location, report_date, color_count, bw_count, total_count)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(ip_address, report_date) DO UPDATE SET
                    model=excluded.model,
                    device_name=excluded.device_name,
                    location=excluded.location,
                    color_count=excluded.color_count,
                    bw_count=excluded.bw_count,
                    total_count=excluded.total_count
                ''', (
                    data.get('ip'), data.get('model'), data.get('name'), data.get('location'),
                    today_str, data.get('color'), data.get('bw'), data.get('sum')
                ))
        con.commit()
        con.close()
        logging.info(f"Zapisano historie licznikow dla {len(counters_data)} drukarek.")
    except Exception as e:
        logging.error(f"Nie udalo sie zapisac historii licznikow w bazie: {e}")

def get_last_known_counter(ip):
    """Pobiera ostatni zapisany stan licznika dla danego IP."""
    try:
        con = sqlite3.connect(DB_FILE)
        con.row_factory = sqlite3.Row # Umożliwia dostęp do kolumn po nazwie
        cur = con.cursor()
        cur.execute('''
            SELECT * FROM counter_history 
            WHERE ip_address = ? 
            ORDER BY report_date DESC 
            LIMIT 1
        ''', (ip,))
        result = cur.fetchone()
        con.close()
        return result
    except Exception as e:
        logging.error(f"Blad odczytu historii licznikow dla {ip}: {e}")
    return None

# --- Funkcje pomocnicze i konfiguracyjne ---
def load_config():
    config = configparser.ConfigParser()
    try:
        config.read(CONFIG_FILE, encoding='utf-8')
    except UnicodeDecodeError:
        logging.warning("Nie udalo sie odczytac config.ini jako UTF-8. Probuje z 'windows-1250'...")
        config.read(CONFIG_FILE, encoding='windows-1250')
    return config

def load_printers():
    """Wczytuje drukarki do monitorowania tonerow i wyswietlania na dashboardzie."""
    printers = []
    try:
        with open(PRINTERS_FILE, mode='r', encoding='utf-8') as infile:
            reader = csv.reader(infile)
            for row in reader:
                if row and row[0].strip():
                    candidate = row[0].strip()
                    try:
                        ipaddress.ip_address(candidate)
                    except ValueError:
                        logging.warning(f"Pominięto niepoprawny adres IP w {PRINTERS_FILE}: {candidate}")
                        continue
                    printers.append({'ip': candidate})
    except FileNotFoundError:
        logging.error(f"KRYTYCZNY BLAD: Nie znaleziono pliku '{PRINTERS_FILE}'!")
    return printers

def load_printers_for_counters():
    """Wczytuje drukarki do raportow licznikow."""
    printers = []
    try:
        with open(PRINTERS_COUNTERS_FILE, mode='r', encoding='utf-8') as infile:
            reader = csv.reader(infile)
            for row in reader:
                if row and row[0].strip():
                    candidate = row[0].strip()
                    try:
                        ipaddress.ip_address(candidate)
                    except ValueError:
                        logging.warning(f"Pominięto niepoprawny adres IP w {PRINTERS_COUNTERS_FILE}: {candidate}")
                        continue
                    printers.append({'ip': candidate})
    except FileNotFoundError:
        logging.warning(f"Plik '{PRINTERS_COUNTERS_FILE}' nie istnieje. Raport licznikow nie zostanie wygenerowany.")
    return printers

def get_custom_oids_for_ip(config, ip):
    section_name = f"CUSTOM_OIDS:{ip}"
    if config.has_section(section_name):
        logging.info(f"[{ip}] Znaleziono niestandardowa konfiguracje OID.")
        return dict(config.items(section_name))
    return {}

def send_email_notification(subject, html_body, config, recipient_key, attachment_path=None, priority=None):
    logging.info(f"Proba wyslania powiadomienia email (klucz: {recipient_key}, priorytet: {priority})")
    smtp_config = config['SMTP']
    sender_email = smtp_config.get('sender_email')
    receiver_emails_str = config['EMAILS'].get(recipient_key)

    if not receiver_emails_str:
        logging.warning(f"Brak adresatow dla klucza '{recipient_key}'. Email nie zostanie wyslany.")
        return False

    receiver_emails = [email.strip() for email in receiver_emails_str.split(',')]
    logging.info(f"Adresaci: {', '.join(receiver_emails)}")

    message = MIMEMultipart("alternative")
    message["From"] = sender_email
    message["To"] = ", ".join(receiver_emails)
    message["Subject"] = subject

    if priority == 'high':
        message['X-Priority'] = '1 (Highest)'
        message['X-MSMail-Priority'] = 'High'
        message['Importance'] = 'High'

    message.attach(MIMEText(html_body, 'html', 'utf-8'))

    if attachment_path and PANDAS_AVAILABLE:
        try:
            with open(attachment_path, "rb") as attachment:
                part = MIMEApplication(attachment.read(), Name=os.path.basename(attachment_path))
            part['Content-Disposition'] = f'attachment; filename="{os.path.basename(attachment_path)}"'
            message.attach(part)
            logging.info(f"Zalaczono plik: {attachment_path}")
        except Exception as e:
            logging.error(f"Nie udalo sie dolaczyc pliku: {e}")
            return False

    try:
        # Wczytaj klucz z pliku
        with open(os.path.join(BASE_DIR, 'secret.key'), 'rb') as key_file:
            key = key_file.read()

        f = Fernet(key)

        # Odczytaj zaszyfrowane hasło z config.ini
        encrypted_password = smtp_config.get('password')
        if not encrypted_password:
            raise ValueError("Brak hasła w pliku konfiguracyjnym.")

        # Odszyfruj hasło
        decrypted_password = f.decrypt(encrypted_password.encode('utf-8')).decode('utf-8')

    except FileNotFoundError:
        logging.critical("KRYTYCZNY BŁĄD: Nie znaleziono pliku klucza 'secret.key'! Nie można wysłać e-maila.")
        return False
    except Exception as e:
        logging.critical(f"KRYTYCZNY BŁĄD: Nie udało się odszyfrować hasła. Błąd: {e}. Sprawdź poprawność klucza i hasła w config.ini.")
        return False

    try:
        server_address = smtp_config.get('server')
        port = int(smtp_config.get('port'))
        logging.info(f"Laczenie z serwerem SMTP: {server_address}:{port}")

        server = smtplib.SMTP(server_address, port, timeout=15)

        if smtp_config.getboolean('use_tls', fallback=False):
            server.starttls()

        if smtp_config.get('user') and decrypted_password:
            server.login(smtp_config.get('user'), decrypted_password)

        server.send_message(message)
        server.quit()
        logging.info(f"Wiadomosc email '{subject}' zostala wyslana pomyslenie.")
        return True
    except socket.timeout:
        logging.error("Timeout podczas laczenia z serwerem SMTP.")
    except Exception as e:
        logging.error(f"Blad podczas wysylania maila: {e}", exc_info=True)
    return False

def print_alert_summary(alert_level, alerts):
    """Wyświetla podsumowanie alertów w terminalu."""
    if not alerts:
        return
        
    print(f"\n{'='*60}")
    print(f"  PODSUMOWANIE ALERTÓW - POZIOM {alert_level}")
    print(f"{'='*60}")
    print(f"Liczba alertów: {len(alerts)}")
    print("-" * 60)
    
    for alert in alerts:
        ip = alert.get('ip', 'N/A')
        location = alert.get('location', 'Brak lokalizacji')
        name = alert.get('name', 'Brak nazwy')
        desc = alert.get('desc', 'N/A')
        level = alert.get('level', 0)
        
        print(f"• {ip} | {location}")
        print(f"  {name}")
        print(f"  Toner: {desc} - Poziom: {level:.1f}%")
        print("-" * 60)
    
    print(f"{'='*60}\n")

# --- Funkcje SNMP ---
async def get_snmp_data_async(ip, oids, community, timeout=5, retries=1, port=161):
    oids = [oid for oid in oids if oid]
    if not oids: return {}
    
    snmp_engine = SnmpEngine()
    transport_target = await UdpTransportTarget.create((ip, port), timeout=timeout, retries=retries)
    results = {}
    
    try:
        object_types = [ObjectType(ObjectIdentity(oid)) for oid in oids]
        error_indication, error_status, error_index, var_binds = await get_cmd(
            snmp_engine, CommunityData(community), transport_target, ContextData(), *object_types
        )
        if error_indication:
            logging.debug(f"[{ip}] Blad SNMP (get_cmd): {error_indication}")
        elif error_status:
            logging.debug(f"[{ip}] Blad statusu SNMP (get_cmd): {error_status.prettyPrint()}")
            for var_oid, val in var_binds:
                if 'noSuch' not in str(val):
                    results[str(var_oid)] = str(val)
        else:
            for var_oid, val in var_binds:
                results[str(var_oid)] = str(val)
    except Exception as e:
        logging.error(f"[{ip}] Wyjatek w get_snmp_data_async: {e}")
    return results

async def get_printer_base_info(ip, community, timeout=5, retries=1, port=161):
    oids = ['1.3.6.1.2.1.25.3.2.1.3.1', '1.3.6.1.2.1.1.5.0', '1.3.6.1.2.1.1.6.0']
    data = await get_snmp_data_async(ip, oids, community, timeout=timeout, retries=retries, port=port)
    model = data.get('1.3.6.1.2.1.25.3.2.1.3.1', "Nie odczytano")
    name = data.get('1.3.6.1.2.1.1.5.0', "Brak")
    location = data.get('1.3.6.1.2.1.1.6.0', "Brak")
    return {'model': model, 'name': name, 'location': location}

async def walk_snmp_oid(ip, community, oid, timeout=10, retries=2, port=161):
    results = {}
    snmp_engine = SnmpEngine()
    transport_target = await UdpTransportTarget.create((ip, port), timeout=timeout, retries=retries)
    var_binds = [ObjectType(ObjectIdentity(oid))]
    while True:
        try:
            error_indication, error_status, error_index, var_bind_table = await next_cmd(
                snmp_engine, CommunityData(community), transport_target, ContextData(), *var_binds
            )
            if error_indication or error_status: break
            var_binds = var_bind_table[0]
            current_oid, current_val = var_binds
            if not str(current_oid).startswith(oid): break
            index = str(current_oid).replace(f"{oid}.", '')
            results[index] = str(current_val)
            var_binds = [var_binds] 
        except Exception as e:
            logging.error(f"[{ip}] Blad podczas 'walk' SNMP dla OID {oid}: {e}")
            break
    return results

async def get_toner_levels_snmp(ip, community, config, custom_oids=None):
    """
    Pobiera poziomy tonerów dla drukarki, optymalizując liczbę zapytań SNMP.
    1. Odkrywa wszystkie materiały eksploatacyjne za pomocą SNMP walk.
    2. Zbiera OIDy dla poziomu bieżącego i maksymalnego wszystkich materiałów.
    3. Wysyła jedno zbiorcze zapytanie SNMP get, aby pobrać wszystkie dane naraz.
    4. Przetwarza wyniki i zwraca listę tonerów z ich poziomami.
    """
    toners = []
    oid_map = custom_oids if custom_oids and custom_oids.get('desc') else {
        'desc': '1.3.6.1.2.1.43.11.1.1.6',
        'max': '1.3.6.1.2.1.43.11.1.1.8',
        'current': '1.3.6.1.2.1.43.11.1.1.9',
        'value_is_percentage': 'false'
    }
    low_status_percent = config.getint('MONITORING', 'toner_low_status_percent', fallback=3)
    snmp_timeout = config.getint('MONITORING', 'snmp_timeout', fallback=5)
    snmp_retries = config.getint('MONITORING', 'snmp_retries', fallback=2)
    snmp_port = config.getint('MONITORING', 'snmp_port', fallback=161)
    base_desc_oid = oid_map.get('desc')
    if not base_desc_oid:
        return []

    # 1. Odkryj materiały przez SNMP walk
    discovered_supplies = await walk_snmp_oid(ip, community, base_desc_oid,
                                              timeout=snmp_timeout, retries=snmp_retries,
                                              port=snmp_port)
    if not discovered_supplies:
        logging.warning(f"[{ip}] Nie znaleziono materialow przez 'walk' dla OID: {base_desc_oid}")
        return []

    # 2. Przygotuj listy OIDów do zbiorczego zapytania
    oids_to_fetch = []
    supply_details = {}
    value_is_percentage = oid_map.get('value_is_percentage', 'false').lower() == 'true'

    for index, desc in discovered_supplies.items():
        current_oid = f"{oid_map.get('current')}.{index}"
        oids_to_fetch.append(current_oid)

        max_oid = None
        if not value_is_percentage:
            max_oid = f"{oid_map.get('max')}.{index}"
            oids_to_fetch.append(max_oid)

        supply_details[index] = {'desc': desc, 'current_oid': current_oid, 'max_oid': max_oid}

    # 3. Wyślij jedno zbiorcze zapytanie SNMP
    logging.info(f"[{ip}] Odpytuje o {len(oids_to_fetch)} OIDow dla {len(discovered_supplies)} materialow...")
    all_levels_data = await get_snmp_data_async(ip, oids_to_fetch, community,
                                                timeout=snmp_timeout, retries=snmp_retries,
                                                port=snmp_port)

    # 4. Przetwórz otrzymane dane
    for index, details in supply_details.items():
        try:
            desc = details['desc']
            current_oid = details['current_oid']
            current_level_str = all_levels_data.get(current_oid)

            if current_level_str is None or current_level_str == '':
                logging.warning(f"[{ip}] Otrzymano pusta wartosc dla '{desc}'. Pomijam.")
                continue

            current_level = int(current_level_str)
            toner_data = {'desc': desc, 'raw_current': current_level, 'status': 'normal'}

            if value_is_percentage:
                toner_data.update({'level': float(current_level), 'raw_max': 100})
            else:
                max_oid = details['max_oid']
                max_level_str = all_levels_data.get(max_oid)

                if max_level_str is None or max_level_str == '':
                    continue
                max_level = int(max_level_str)
                toner_data['raw_max'] = max_level

                if current_level == -3:
                    toner_data.update({'level': float(low_status_percent), 'status': 'low'})
                elif max_level == -2:
                    toner_data.update({'level': 100.0, 'status': 'new'})
                elif max_level > 0 and current_level >= 0:
                    toner_data['level'] = min((current_level / max_level) * 100, 100.0)
                else:
                    continue  # Pomiń, jeśli dane są nieprawidłowe

            toners.append(toner_data)
        except (ValueError, TypeError, ZeroDivisionError) as e:
            logging.warning(f"[{ip}] Nie mozna przetworzyc danych dla '{details['desc']}'. Blad: {e}")
            continue

    logging.info(f"[{ip}] Przetworzono dane dla {len(toners)} tonerow.")
    return toners

# --- FUNKCJE DLA LICZNIKOW ---

def init_selenium_driver(config):
    """Inicjalizuje i zwraca instancje sterownika Selenium Chrome."""
    try:
        logging.info("Inicjalizacja sterownika Selenium...")
        chrome_options = Options()
        chrome_options.binary_location = config['WWW']['chrome_binary']
        if config['WWW'].getboolean('headless', fallback=True):
            chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument('--blink-settings=imagesEnabled=false')
        chrome_options.set_capability('acceptInsecureCerts', True)
        driver = webdriver.Chrome(options=chrome_options)
        logging.info("Sterownik Selenium zostal uruchomiony.")
        return driver
    except Exception as e:
        logging.error(f"Nie udalo sie zainicjalizowac sterownika Selenium: {e}")
        return None


async def get_counters_snmp(ip, community, model_name="", custom_oids=None,
                            timeout=5, retries=1, port=161):
    """
    Odczytuje liczniki stron przez SNMP.
    Jeśli zdefiniowano niestandardowe OID-y dla liczników, używa ich.
    W przeciwnym razie, używa ogólnego OID-a dla sumy stron jako fallback.
    """
    if custom_oids and custom_oids.get('oid_color_count') and custom_oids.get('oid_bw_count'):
        logging.info(f"[{ip}] Używam niestandardowych OID-ów do odczytu liczników stron.")
        color_oid = custom_oids.get('oid_color_count')
        bw_oid = custom_oids.get('oid_bw_count')
        data = await get_snmp_data_async(ip, [color_oid, bw_oid], community,
                                         timeout=timeout, retries=retries, port=port)

        color_count_str = data.get(color_oid)
        bw_count_str = data.get(bw_oid)

        try:
            if color_count_str is None and bw_count_str is None:
                logging.warning(f"[{ip}] Niestandardowe OID-y liczników nie zwróciły żadnych wartości.")
                return None

            color_count = int(color_count_str) if color_count_str is not None else 0
            bw_count = int(bw_count_str) if bw_count_str is not None else 0
            return {'color': color_count, 'bw': bw_count, 'sum': color_count + bw_count, 'status': 'OK'}
        except (ValueError, TypeError) as e:
            logging.warning(f"[{ip}] Nie udało się przetworzyć niestandardowych wartości liczników SNMP. Sprawdź OID-y. Błąd: {e}")
            return None

    logging.info(f"[{ip}] Uzywam ogolnej metody SNMP do odczytu sumy licznikow (Fallback).")
    total_oid = '1.3.6.1.2.1.43.10.2.1.4.1.1'
    total_data = await get_snmp_data_async(ip, [total_oid], community,
                                           timeout=timeout, retries=retries, port=port)
    total_count = total_data.get(total_oid)
    if total_count:
        try:
            total = int(total_count)
            # Assume total is black & white if color is not specified
            return {'color': 0, 'bw': total, 'sum': total, 'status': 'OK'}
        except (ValueError, TypeError):
            logging.warning(f"[{ip}] Nie udalo sie przetworzyc sumy licznika SNMP.")
    return None

def get_web_data_with_selenium(driver, ip_address):
    """Pobiera dane przez HTTP, używając WebDriverWait dla większej stabilności."""
    try:
        logging.info(f"[{ip_address}] Rozpoczynam próbę web scrapingu przez HTTP...")
        web_data = {'status': 'OK'}
        wait = WebDriverWait(driver, 25)

        # Pobierz informacje o urządzeniu
        driver.get(f"http://{ip_address}/?MAIN=DEVICE")
        wait.until(EC.frame_to_be_available_and_switch_to_it((By.NAME, "TopLevelFrame")))
        wait.until(EC.frame_to_be_available_and_switch_to_it((By.NAME, "contents")))
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        name_tag = soup.find(id='DeviceName')
        if name_tag: web_data['name'] = name_tag.get_text(strip=True)
        location_tag = soup.find(id='DeviceLocation')
        if location_tag: web_data['location'] = location_tag.get_text(strip=True)
        driver.switch_to.default_content()

        # Pobierz informacje o licznikach
        driver.get(f"http://{ip_address}/?MAIN=COUNTER&SUB=TOTAL")
        wait.until(EC.frame_to_be_available_and_switch_to_it((By.NAME, "TopLevelFrame")))
        wait.until(EC.frame_to_be_available_and_switch_to_it((By.NAME, "contents")))
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        color_cell = soup.find('td', id='TotalFullColor')
        if color_cell: web_data['color'] = int(color_cell.get_text(strip=True))
        bw_cell = soup.find('td', id='TotalBlackColor')
        if bw_cell: web_data['bw'] = int(bw_cell.get_text(strip=True))
        driver.switch_to.default_content()

        if web_data.get('color') is None or web_data.get('bw') is None:
             logging.warning(f"[{ip_address}] Połączono, ale nie znaleziono elementów licznika na stronie.")
             return None
        
        logging.info(f"[{ip_address}] Web scraping zakończony sukcesem.")
        return web_data

    except (TimeoutException, WebDriverException) as e:
        logging.warning(f"[{ip_address}] Web scraping nie powiódł się: {type(e).__name__}")
        driver.switch_to.default_content()
        return 'offline'
    except Exception as e:
        logging.error(f"[{ip_address}] Niespodziewany błąd podczas web scrapingu: {e}", exc_info=True)
        driver.switch_to.default_content()
        return None

# --- GŁÓWNE FUNKCJE ZADAŃ ---

def scrape_all_with_selenium(ips, config, max_workers=None):
    """Web scraping wielu drukarek rownolegle (osobny driver Chromium na watek).

    Zwraca {ip: wynik} - wynik jak z get_web_data_with_selenium (dict/'offline'/None).
    """
    if max_workers is None:
        max_workers = config.getint('MONITORING', 'web_workers', fallback=WEB_WORKERS_DEFAULT)
    results = {}

    def _scrape_one(ip):
        driver = init_selenium_driver(config)
        if not driver:
            logging.error(f"[{ip}] Nie udalo sie zainicjalizowac sterownika Selenium.")
            return ip, None
        try:
            return ip, get_web_data_with_selenium(driver, ip)
        finally:
            driver.quit()

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for ip, result in executor.map(_scrape_one, ips):
            results[ip] = result
    return results


async def check_toner_and_counters(force_email=False, ip_to_test=None):
    """ZINTEGROWANA funkcja do sprawdzania tonerow i licznikow."""
    config = load_config()
    printers = [{'ip': ip_to_test}] if ip_to_test else load_printers()
    if ip_to_test: logging.info(f"Test dla pojedynczej drukarki: {ip_to_test}")

    community = config.get('MONITORING', 'snmp_community', fallback='public')
    threshold_low = config.getint('MONITORING', 'toner_threshold_low', fallback=20)
    threshold_critical = config.getint('MONITORING', 'toner_threshold_critical', fallback=5)
    exclude_keywords = [kw.strip().lower() for kw in config.get('MONITORING', 'toner_exclude_keywords', fallback='waste').split(',')]
    alert_cooldown_days = config.getint('MONITORING', 'alert_cooldown_days', fallback=3)
    
    low_toner_alerts = []
    critical_toner_alerts = []
    all_toners_data_for_db = []
    all_counters_data = []
    snmp_timeout = config.getint('MONITORING', 'snmp_timeout', fallback=5)
    snmp_retries = config.getint('MONITORING', 'snmp_retries', fallback=2)
    snmp_port = config.getint('MONITORING', 'snmp_port', fallback=161)

    if not printers:
        logging.warning("Brak drukarek w printers.csv. Zatrzymuje sprawdzanie.")
        return

    logging.info(f"Sprawdzanie tonerow i licznikow dla {len(printers)} drukarek...")
    ip_list = [p['ip'] for p in printers if p.get('ip')]
    web_data_map = scrape_all_with_selenium(ip_list, config)

    for printer in printers:
        ip = printer['ip']
        if not ip: continue
        try:
            logging.info(f"--- Przetwarzanie drukarki: {ip} ---")
            base_info = await get_printer_base_info(ip, community, timeout=snmp_timeout,
                                                    retries=snmp_retries, port=snmp_port)
            
            # --- Zbieranie danych o tonerach ---
            custom_oids = get_custom_oids_for_ip(config, ip)
            toners = await get_toner_levels_snmp(ip, community, config, custom_oids)
            
            if not toners:
                logging.warning(f"Brak danych o tonerach z {ip}.")
            else:
                for toner in toners:
                    toner_db_entry = {'ip': ip, **base_info, **toner}
                    all_toners_data_for_db.append(toner_db_entry)

                    desc_lower = toner.get('desc', '').lower()
                    if any(keyword in desc_lower for keyword in exclude_keywords):
                        continue
                    if 'level' not in toner: continue

                    alert_base = {'ip': ip, **base_info, **toner}
                    level = toner.get('level')
                    status = toner.get('status')
                    
                    last_alert_time = get_last_alert_timestamp(ip, toner.get('desc'))
                    cooldown_active = False
                    if last_alert_time and (datetime.now() - last_alert_time) < timedelta(days=alert_cooldown_days):
                        cooldown_active = True

                    if not cooldown_active:
                        if status == 'low': low_toner_alerts.append(alert_base)
                        elif level <= threshold_critical: critical_toner_alerts.append(alert_base)
                        elif level <= threshold_low: low_toner_alerts.append(alert_base)
                    elif status == 'low' or level <= threshold_low:
                        logging.info(f"[{ip}] Alert dla '{toner.get('desc')}' jest w okresie blokady. Pomijam wysylke email.")
            
            # --- Zbieranie danych o licznikach ---
            logging.info(f"[{ip}] Rozpoczynam odczyt licznikow...")
            counter_data_row = {'ip': ip, **base_info}
            web_data = web_data_map.get(ip)
            
            if web_data and web_data != 'offline':
                if not web_data.get('name'): web_data['name'] = base_info.get('name')
                if not web_data.get('location'): web_data['location'] = base_info.get('location')
                counter_data_row.update(web_data)
                counter_data_row['sum'] = counter_data_row.get('color', 0) + counter_data_row.get('bw', 0)
            else:
                snmp_counters = await get_counters_snmp(ip, community, base_info.get('model'),
                                                        custom_oids, timeout=snmp_timeout,
                                                        retries=snmp_retries, port=snmp_port)
                if snmp_counters:
                    counter_data_row.update(snmp_counters)
                elif web_data == 'offline':
                    counter_data_row.update({'name': 'DRUKARKA OFFLINE (TIMEOUT)', 'status': 'OFFLINE'})
                else:
                    counter_data_row.update({'name': 'WYSTAPIL BLAD ODCZYTU', 'status': 'ERROR'})
            all_counters_data.append(counter_data_row)
        except Exception as e:
            logging.error(f"[{ip}] Nieoczekiwany blad przetwarzania drukarki: {e}", exc_info=True)
            continue

    if all_toners_data_for_db: update_toner_status_in_db(all_toners_data_for_db)
    if all_counters_data: save_counter_history(all_counters_data)

    today = datetime.now().strftime("%Y-%m-%d %H:%M")

    if critical_toner_alerts:
        subject = f"[PILNE] Krytyczny poziom tonerow ({len(critical_toner_alerts)} alertow)"
        html_body = create_html_report(critical_toner_alerts, today, "Toner", "critical")
        print_alert_summary("KRYTYCZNY", critical_toner_alerts)
        if force_email:
            sent = send_email_notification(subject, html_body, config, 'recipient_email_toner_critical', priority='high')
            if sent:
                update_alert_timestamp(critical_toner_alerts)
    
    if low_toner_alerts:
        subject = f"[UWAGA] Niski poziom tonerow ({len(low_toner_alerts)} alertow)"
        html_body = create_html_report(low_toner_alerts, today, "Toner", "low")
        print_alert_summary("NISKI", low_toner_alerts)
        if force_email:
            sent = send_email_notification(subject, html_body, config, 'recipient_email_toner_low')
            if sent:
                update_alert_timestamp(low_toner_alerts)

    if not critical_toner_alerts and not low_toner_alerts:
        logging.info("✓ Nie wykryto nowych alertow tonerowych wymagajacych powiadomienia.")
    
    log_script_run('toner_check')

async def report_counters(force_email=False, ip_to_test=None):
    """
    Zbiera dane o licznikach, generuje raporty (HTML, Excel)
    i opcjonalnie wysyla je mailem. W przypadku braku odpowiedzi od drukarki,
    uzywa ostatniego znanego stanu z bazy danych.
    """
    config = load_config()
    # Użyj nowej funkcji do wczytania drukarek do raportu
    printers = [{'ip': ip_to_test}] if ip_to_test else load_printers_for_counters()
    if not printers:
        logging.warning("Brak drukarek w pliku printers_counters.csv. Zatrzymuje generowanie raportu.")
        return

    if ip_to_test:
        logging.info(f"Test raportu licznikow dla pojedynczej drukarki: {ip_to_test}")

    community = config.get('MONITORING', 'snmp_community', fallback='public')
    snmp_timeout = config.getint('MONITORING', 'snmp_timeout', fallback=5)
    snmp_retries = config.getint('MONITORING', 'snmp_retries', fallback=2)
    snmp_port = config.getint('MONITORING', 'snmp_port', fallback=161)
    all_counters_data = []

    logging.info(f"Zbieranie danych o licznikach dla {len(printers)} drukarek...")
    ip_list = [p['ip'] for p in printers if p.get('ip')]
    web_data_map = scrape_all_with_selenium(ip_list, config)

    for printer in printers:
        ip = printer['ip']
        if not ip: continue
        try:
            logging.info(f"--- Przetwarzanie licznikow dla: {ip} ---")
            base_info = await get_printer_base_info(ip, community, timeout=snmp_timeout,
                                                    retries=snmp_retries, port=snmp_port)
            counter_data_row = {'ip': ip, **base_info}
            
            # Proba odczytu na żywo
            custom_oids = get_custom_oids_for_ip(config, ip)
            web_data = web_data_map.get(ip)
            
            if web_data and web_data != 'offline':
                if not web_data.get('name'): web_data['name'] = base_info.get('name')
                if not web_data.get('location'): web_data['location'] = base_info.get('location')
                counter_data_row.update(web_data)
                counter_data_row['sum'] = counter_data_row.get('color', 0) + counter_data_row.get('bw', 0)
            else:
                snmp_counters = await get_counters_snmp(ip, community, base_info.get('model'),
                                                        custom_oids, timeout=snmp_timeout,
                                                        retries=snmp_retries, port=snmp_port)
                if snmp_counters:
                    counter_data_row.update(snmp_counters)
                else:
                    # ---- NOWA LOGIKA FALLBACKU ----
                    logging.warning(f"[{ip}] Drukarka nie odpowiada. Szukam ostatnich danych w bazie...")
                    last_known = get_last_known_counter(ip)
                    if last_known:
                        last_date = last_known['report_date']
                        counter_data_row.update({
                            'name': last_known['device_name'],
                            'location': last_known['location'],
                            'model': last_known['model'],
                            'color': last_known['color_count'],
                            'bw': last_known['bw_count'],
                            'sum': last_known['total_count'],
                            'status': 'HISTORY',
                            'comment': f"OFFLINE - dane z {last_date}"
                        })
                        logging.info(f"[{ip}] Znaleziono dane historyczne z dnia {last_date}.")
                    else:
                        if web_data == 'offline':
                            counter_data_row.update({'name': 'DRUKARKA OFFLINE', 'status': 'OFFLINE', 'comment': 'Brak danych w bazie'})
                        else:
                            counter_data_row.update({'name': 'BŁĄD ODCZYTU', 'status': 'ERROR', 'comment': 'Brak danych w bazie'})

            all_counters_data.append(counter_data_row)
        except Exception as e:
            logging.error(f"[{ip}] Nieoczekiwany blad przetwarzania licznikow: {e}", exc_info=True)
            continue

    if all_counters_data:
        # Zapisz tylko aktualne dane do historii
        current_data_to_save = [d for d in all_counters_data if d.get('status') == 'OK']
        if current_data_to_save:
            save_counter_history(current_data_to_save)
        
        logging.info(f"Zebrano dane dla {len(all_counters_data)} licznikow (w tym historyczne).")

        if force_email:
            logging.info("Wymuszono wyslanie raportu licznikow e-mailem.")
            today_str = datetime.now().strftime("%Y-%m-%d")
            
            html_body = create_html_report(all_counters_data, today_str, report_type="Counters")
            excel_filename = f"Raport_Licznikow_{today_str}.xlsx"
            excel_filepath = os.path.join(BASE_DIR, excel_filename)
            attachment_path = create_excel_report(all_counters_data, excel_filepath)

            subject = f"Raport liczników drukarek z dnia {today_str}"
            send_email_notification(
                subject, html_body, config, 'recipient_email_counters',
                attachment_path=attachment_path
            )

            if attachment_path and os.path.exists(attachment_path):
                 os.remove(attachment_path)
                 logging.info(f"Usunieto tymczasowy plik raportu: {attachment_path}")
        else:
            logging.info("Dane licznikow zostaly zebrane. Uzyj opcji --force-counters-email, aby wyslac raport.")
    else:
        logging.warning("Nie udalo sie zebrac zadnych danych o licznikach.")
        
    log_script_run('counters_report')

def create_excel_report(report_data, filename):
    if not PANDAS_AVAILABLE: return None
    df_data = []
    # Usunięto filtrowanie - teraz wszystkie dane trafiają do raportu
    for d in report_data:
        df_data.append({
            'Adres IP': d.get('ip'),
            'Lokalizacja': d.get('location'),
            'Nazwa': d.get('name'),
            'Model': d.get('model'),
            'Licznik Kolor': d.get('color'),
            'Licznik B&W': d.get('bw'),
            'Suma': d.get('sum'),
            'Uwagi': d.get('comment', '') # Nowa kolumna na uwagi
        })
    df = pd.DataFrame(df_data)
    # Definiowanie kolejności kolumn
    df = df[['Adres IP', 'Lokalizacja', 'Nazwa', 'Model', 'Licznik Kolor', 'Licznik B&W', 'Suma', 'Uwagi']]
    df.to_excel(filename, index=False, engine='openpyxl')
    logging.info(f"Raport Excel zapisany do: {filename}")
    return filename

def _esc(value):
    """Escaping HTML dla danych pochodzacych z urzadzen (W6)."""
    return html.escape(str(value if value is not None else ''))


def create_html_report(report_data, today_str, report_type="Toner", alert_level="low"):
    is_toner_report = report_type == "Toner"
    
    # ... (początek funkcji bez zmian)
    if is_toner_report:
        if alert_level == 'critical':
            title = "PILNE: Krytyczny poziom tonerów"
            message = "<p style='text-align:center; font-size:14px;'>Wymagana jest <b>natychmiastowa wymiana</b> poniższych materiałów eksploatacyjnych!</p>"
        else: # low
            title = "UWAGA: Niski poziom tonerów"
            message = "<p style='text-align:center; font-size:14px;'>Proszę zweryfikować stany magazynowe, a następnie zamówić wymienione materiały.</p>"
    else:
        title = "Raport liczników drukarek"
        message = ""

    html = f"""
    <html><head><style>
        body{{font-family:Arial,sans-serif;margin:20px}}
        table{{border-collapse:collapse;width:95%;margin:auto}}
        th,td{{border:1px solid #cccccc;text-align:left;padding:10px;font-size:12px}}
        th{{background-color:#eeeeee;font-weight:bold}}
        tr.low{{background-color:#fff9c4;}}
        tr.critical{{background-color:#b71c1c; color: white; font-weight: bold;}}
        tr.summary{{font-weight:bold;background-color:#f0f0f0;}}
        tr.history td {{ background-color: #f5f5f5; color: #555; font-style: italic; }}
        tr.offline-error td {{
            color: #d9534f;
            font-weight: bold;
            text-transform: uppercase;
            text-align: center;
            background-color: #f2dede;
        }}
        h2{{text-align:center}}
    </style></head><body>
    <h2>{title} na dzien {today_str}</h2>
    {message}
    <table><tr>
    """
    
    headers = ['IP', 'Lokalizacja', 'Nazwa', 'Model', 'Nazwa Tonera', 'Poziom %'] if is_toner_report else ['IP', 'Lokalizacja', 'Nazwa', 'Model', 'Kolor', 'B&W', 'Suma', 'Uwagi']
    for header in headers: html += f"<th>{header}</th>"
    html += "</tr>"
    total_color, total_bw, total_sum = 0, 0, 0

    for data in report_data:
        if is_toner_report:
            row_class = alert_level
        else:
            status = data.get('status', '')
            if status == 'HISTORY': row_class = 'history'
            elif status in ['OFFLINE', 'ERROR']: row_class = 'offline-error'
            else: row_class = ''
            
        html += f"<tr class='{row_class}'>"

        if is_toner_report:
            html += (f"<td>{_esc(data.get('ip', ''))}</td>"
                     f"<td>{_esc(data.get('location', ''))}</td>"
                     f"<td>{_esc(data.get('name', ''))}</td>"
                     f"<td>{_esc(data.get('model', ''))}</td>"
                     f"<td>{_esc(data.get('desc', ''))}</td>"
                     f"<td><b>{data.get('level', 0.0):.1f}%</b></td>")
        else:
            if data.get('status') in ['OFFLINE', 'ERROR']:
                html += (f"<td class='offline-error' colspan='{len(headers)}'>"
                         f"Drukarka {_esc(data.get('ip'))} - {_esc(data.get('name'))} "
                         f"({_esc(data.get('comment', ''))})</td>")
            else:
                html += (f"<td>{_esc(data.get('ip', ''))}</td>"
                         f"<td>{_esc(data.get('location', 'Brak'))}</td>"
                         f"<td>{_esc(data.get('name', 'Brak'))}</td>"
                         f"<td>{_esc(data.get('model', 'Brak'))}</td>"
                         f"<td>{_esc(data.get('color', 'N/A'))}</td>"
                         f"<td>{_esc(data.get('bw', 'N/A'))}</td>"
                         f"<td>{_esc(data.get('sum', 'N/A'))}</td>"
                         f"<td>{_esc(data.get('comment', ''))}</td>")
                if isinstance(data.get('color'), int): total_color += data.get('color', 0)
                if isinstance(data.get('bw'), int): total_bw += data.get('bw', 0)
                if isinstance(data.get('sum'), int): total_sum += data.get('sum', 0)
        html += "</tr>"
    if not is_toner_report:
        html += f"<tr class='summary'><td colspan='4' style='text-align:right;'>SUMA:</td><td>{total_color}</td><td>{total_bw}</td><td>{total_sum}</td><td></td></tr>"
    html += "</table></body></html>"
    return html

# --- Glowna logika programu ---
async def main():
    parser = argparse.ArgumentParser(description="Monitorowanie Drukarek.")
    parser.add_argument('--check-toner', action='store_true', help='Sprawdza poziom tonerow i zapisuje alerty.')
    parser.add_argument('--force-toner-email', action='store_true', help='Wymusza wyslanie alertu o tonerach (uzywac z --check-toner).')
    
    parser.add_argument('--report-counters', action='store_true', help='Zbiera dane o licznikach i generuje raport.')
    parser.add_argument('--force-counters-email', action='store_true', help='Wysyla wygenerowany raport licznikow e-mailem (uzywac z --report-counters).')

    parser.add_argument('--ip', '-i', type=str, help='Sprawdza tylko jedna drukarke o podanym IP.')
    args = parser.parse_args()
    
    init_db() 

    if args.check_toner:
        # Uruchamia tylko sprawdzanie tonerow i zintegrowane zbieranie danych
        await check_toner_and_counters(args.force_toner_email, args.ip)
    elif args.report_counters:
        # Uruchamia dedykowana funkcje do raportowania licznikow
        await report_counters(args.force_counters_email, args.ip)
    else:
        print("Wybierz jedna z opcji: --check-toner lub --report-counters.")
        parser.print_help()

if __name__ == "__main__":
    setup_logging()

    if not PANDAS_AVAILABLE:
        logging.warning("UWAGA: 'pandas' i 'openpyxl' nie sa zainstalowane. Raporty Excel nie beda dzialac.")

    if not lockfile.acquire(LOCK_FILE, max_age_seconds=3600):
        logging.error("Inny proces monitoringu dziala (aktywna blokada). Koniec przebiegu.")
        sys.exit(1)

    try:
        asyncio.run(main())
    except Exception as e:
        logging.critical(f"Wystapil nieoczekiwany blad: {e}")
    finally:
        lockfile.release(LOCK_FILE)
        logging.info("Blokada zwolniona.")
