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

# Imports for Excel reports
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
    """Initialize the database and create/update tables."""
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
        logging.info(f"Database '{DB_FILE}' initialized/updated.")
    except Exception as e:
        logging.error(f"Failed to initialize the database: {e}")

def log_script_run(run_type):
    """Record the timestamp of the last script run."""
    try:
        con = sqlite3.connect(DB_FILE)
        cur = con.cursor()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur.execute('INSERT INTO script_runs (run_type, run_timestamp) VALUES (?, ?)', (run_type, now))
        con.commit()
        con.close()
        logging.info(f"Recorded script run: {run_type} at {now}")
    except Exception as e:
        logging.error(f"Failed to record script run info: {e}")

def update_toner_status_in_db(toner_data):
    """Save or update toner status in the database."""
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
        logging.info(f"Updated {len(toner_data)} toner entries in the database.")
    except Exception as e:
        logging.error(f"Failed to update data in the database: {e}")

def update_alert_timestamp(alerts):
    """Update the alert-sent timestamp for the given toners."""
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
        logging.info(f"Updated alert-sent timestamps for {len(alerts)} toners.")
    except Exception as e:
        logging.error(f"Failed to update alert timestamps in the database: {e}")

def get_last_alert_timestamp(ip, desc):
    """Get the last alert date for the given toner."""
    try:
        con = sqlite3.connect(DB_FILE)
        cur = con.cursor()
        cur.execute('SELECT alert_sent_timestamp FROM toner_status WHERE ip_address = ? AND toner_desc = ?', (ip, desc))
        result = cur.fetchone()
        con.close()
        if result and result[0]:
            return datetime.fromisoformat(result[0])
    except Exception as e:
        logging.error(f"Error reading alert timestamp from the database: {e}")
    return None

def save_counter_history(counters_data):
    """Save counter history to the database."""
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
        logging.info(f"Saved counter history for {len(counters_data)} printers.")
    except Exception as e:
        logging.error(f"Failed to save counter history in the database: {e}")

def get_last_known_counter(ip):
    """Get the last known counter state for the given IP."""
    try:
        con = sqlite3.connect(DB_FILE)
        con.row_factory = sqlite3.Row # Enables column access by name
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
        logging.error(f"Error reading counter history for {ip}: {e}")
    return None

# --- Funkcje pomocnicze i konfiguracyjne ---
def load_config():
    config = configparser.ConfigParser()
    try:
        config.read(CONFIG_FILE, encoding='utf-8')
    except UnicodeDecodeError:
        logging.warning("Failed to read config.ini as UTF-8. Trying 'windows-1250'...")
        config.read(CONFIG_FILE, encoding='windows-1250')
    return config

def load_printers():
    """Load printers for toner monitoring and dashboard display."""
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
                        logging.warning(f"Skipped invalid IP address in {PRINTERS_FILE}: {candidate}")
                        continue
                    printers.append({'ip': candidate})
    except FileNotFoundError:
        logging.error(f"CRITICAL ERROR: file '{PRINTERS_FILE}' not found!")
    return printers

def load_printers_for_counters():
    """Load printers for counter reports."""
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
                        logging.warning(f"Skipped invalid IP address in {PRINTERS_COUNTERS_FILE}: {candidate}")
                        continue
                    printers.append({'ip': candidate})
    except FileNotFoundError:
        logging.warning(f"File '{PRINTERS_COUNTERS_FILE}' does not exist. The counter report will not be generated.")
    return printers

def get_custom_oids_for_ip(config, ip):
    section_name = f"CUSTOM_OIDS:{ip}"
    if config.has_section(section_name):
        logging.info(f"[{ip}] Custom OID configuration found.")
        return dict(config.items(section_name))
    return {}

def send_email_notification(subject, html_body, config, recipient_key, attachment_path=None, priority=None):
    logging.info(f"Attempting to send e-mail notification (key: {recipient_key}, priority: {priority})")
    smtp_config = config['SMTP']
    sender_email = smtp_config.get('sender_email')
    receiver_emails_str = config['EMAILS'].get(recipient_key)

    if not receiver_emails_str:
        logging.warning(f"No recipients for key '{recipient_key}'. E-mail will not be sent.")
        return False

    receiver_emails = [email.strip() for email in receiver_emails_str.split(',')]
    logging.info(f"Recipients: {', '.join(receiver_emails)}")

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
            logging.info(f"Attached file: {attachment_path}")
        except Exception as e:
            logging.error(f"Failed to attach file: {e}")
            return False

    try:
        # Wczytaj klucz z pliku
        with open(os.path.join(BASE_DIR, 'secret.key'), 'rb') as key_file:
            key = key_file.read()

        f = Fernet(key)

        # Read the encrypted password from config.ini
        encrypted_password = smtp_config.get('password')
        if not encrypted_password:
            raise ValueError("No password in the configuration file.")

        # Decrypt the password
        decrypted_password = f.decrypt(encrypted_password.encode('utf-8')).decode('utf-8')

    except FileNotFoundError:
        logging.critical("CRITICAL ERROR: key file 'secret.key' not found! Cannot send e-mail.")
        return False
    except Exception as e:
        logging.critical(f"CRITICAL ERROR: failed to decrypt the password. Error: {e}. Check the key and password in config.ini.")
        return False

    try:
        server_address = smtp_config.get('server')
        port = int(smtp_config.get('port'))
        logging.info(f"Connecting to SMTP server: {server_address}:{port}")

        server = smtplib.SMTP(server_address, port, timeout=15)

        if smtp_config.getboolean('use_tls', fallback=False):
            server.starttls()

        if smtp_config.get('user') and decrypted_password:
            server.login(smtp_config.get('user'), decrypted_password)

        server.send_message(message)
        server.quit()
        logging.info(f"E-mail '{subject}' sent successfully.")
        return True
    except socket.timeout:
        logging.error("Timeout while connecting to the SMTP server.")
    except Exception as e:
        logging.error(f"Error while sending e-mail: {e}", exc_info=True)
    return False

def print_alert_summary(alert_level, alerts):
    """Print an alert summary to the terminal."""
    if not alerts:
        return
        
    print(f"\n{'='*60}")
    print(f"  ALERT SUMMARY - LEVEL {alert_level}")
    print(f"{'='*60}")
    print(f"Number of alerts: {len(alerts)}")
    print("-" * 60)
    
    for alert in alerts:
        ip = alert.get('ip', 'N/A')
        location = alert.get('location', 'Brak lokalizacji')
        name = alert.get('name', 'Brak nazwy')
        desc = alert.get('desc', 'N/A')
        level = alert.get('level', 0)
        
        print(f"- {ip} | {location}")
        print(f"  {name}")
        print(f"  Toner: {desc} - Level: {level:.1f}%")
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
    model = data.get('1.3.6.1.2.1.25.3.2.1.3.1', "Not read")
    name = data.get('1.3.6.1.2.1.1.5.0', "None")
    location = data.get('1.3.6.1.2.1.1.6.0', "None")
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
            logging.error(f"[{ip}] Error during SNMP 'walk' for OID {oid}: {e}")
            break
    return results

async def get_toner_levels_snmp(ip, community, config, custom_oids=None):
    """
    Fetch toner levels for a printer, optimizing the number of SNMP requests.
    1. Discover all consumables via an SNMP walk.
    2. Collect OIDs for current and maximum levels of all consumables.
    3. Send a single bulk SNMP get to fetch all data at once.
    4. Process the results and return a list of toners with their levels.
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

    # 1. Discover consumables via an SNMP walk
    discovered_supplies = await walk_snmp_oid(ip, community, base_desc_oid,
                                              timeout=snmp_timeout, retries=snmp_retries,
                                              port=snmp_port)
    if not discovered_supplies:
        logging.warning(f"[{ip}] No consumables found by 'walk' for OID: {base_desc_oid}")
        return []

    # 2. Prepare OID lists for the bulk request
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

    # 3. Send a single bulk SNMP request
    logging.info(f"[{ip}] Fetching {len(oids_to_fetch)} OIDs for {len(discovered_supplies)} consumables...")
    all_levels_data = await get_snmp_data_async(ip, oids_to_fetch, community,
                                                timeout=snmp_timeout, retries=snmp_retries,
                                                port=snmp_port)

    # 4. Process the received data
    for index, details in supply_details.items():
        try:
            desc = details['desc']
            current_oid = details['current_oid']
            current_level_str = all_levels_data.get(current_oid)

            if current_level_str is None or current_level_str == '':
                logging.warning(f"[{ip}] Empty value received for '{desc}'. Skipping.")
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
                    continue  # Skip if the data is invalid

            toners.append(toner_data)
        except (ValueError, TypeError, ZeroDivisionError) as e:
            logging.warning(f"[{ip}] Cannot process data for '{details['desc']}'. Error: {e}")
            continue

    logging.info(f"[{ip}] Processed data for {len(toners)} toners.")
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
        logging.info("Selenium driver started.")
        return driver
    except Exception as e:
        logging.error(f"Failed to initialize the Selenium driver: {e}")
        return None


async def get_counters_snmp(ip, community, model_name="", custom_oids=None,
                            timeout=5, retries=1, port=161):
    """
    Reads page counters over SNMP.
    If custom OIDs are defined for counters, they are used.
    Otherwise, a generic total-pages OID is used as a fallback.
    """
    if custom_oids and custom_oids.get('oid_color_count') and custom_oids.get('oid_bw_count'):
        logging.info(f"[{ip}] Using custom OIDs to read page counters.")
        color_oid = custom_oids.get('oid_color_count')
        bw_oid = custom_oids.get('oid_bw_count')
        data = await get_snmp_data_async(ip, [color_oid, bw_oid], community,
                                         timeout=timeout, retries=retries, port=port)

        color_count_str = data.get(color_oid)
        bw_count_str = data.get(bw_oid)

        try:
            if color_count_str is None and bw_count_str is None:
                logging.warning(f"[{ip}] Custom counter OIDs returned no values.")
                return None

            color_count = int(color_count_str) if color_count_str is not None else 0
            bw_count = int(bw_count_str) if bw_count_str is not None else 0
            return {'color': color_count, 'bw': bw_count, 'sum': color_count + bw_count, 'status': 'OK'}
        except (ValueError, TypeError) as e:
            logging.warning(f"[{ip}] Failed to process custom SNMP counter values. Check the OIDs. Error: {e}")
            return None

    logging.info(f"[{ip}] Using the generic SNMP method to read the total counter (fallback).")
    total_oid = '1.3.6.1.2.1.43.10.2.1.4.1.1'
    total_data = await get_snmp_data_async(ip, [total_oid], community,
                                           timeout=timeout, retries=retries, port=port)
    total_count = total_data.get(total_oid)
    if total_count:
        try:
            total = int(total_count)
            # Assume the total is black & white if color is not specified
            return {'color': 0, 'bw': total, 'sum': total, 'status': 'OK'}
        except (ValueError, TypeError):
            logging.warning(f"[{ip}] Failed to process the SNMP total counter.")
    return None

def get_web_data_with_selenium(driver, ip_address):
    """Fetch data over HTTP, using WebDriverWait for greater stability."""
    try:
        logging.info(f"[{ip_address}] Starting web scraping over HTTP...")
        web_data = {'status': 'OK'}
        wait = WebDriverWait(driver, 25)

        # Fetch device information
        driver.get(f"http://{ip_address}/?MAIN=DEVICE")
        wait.until(EC.frame_to_be_available_and_switch_to_it((By.NAME, "TopLevelFrame")))
        wait.until(EC.frame_to_be_available_and_switch_to_it((By.NAME, "contents")))
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        name_tag = soup.find(id='DeviceName')
        if name_tag: web_data['name'] = name_tag.get_text(strip=True)
        location_tag = soup.find(id='DeviceLocation')
        if location_tag: web_data['location'] = location_tag.get_text(strip=True)
        driver.switch_to.default_content()

        # Fetch counter information
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
             logging.warning(f"[{ip_address}] Connected, but no counter elements found on the page.")
             return None
        
        logging.info(f"[{ip_address}] Web scraping completed successfully.")
        return web_data

    except (TimeoutException, WebDriverException) as e:
        logging.warning(f"[{ip_address}] Web scraping failed: {type(e).__name__}")
        driver.switch_to.default_content()
        return 'offline'
    except Exception as e:
        logging.error(f"[{ip_address}] Unexpected error during web scraping: {e}", exc_info=True)
        driver.switch_to.default_content()
        return None

# --- MAIN TASK FUNCTIONS ---

def scrape_all_with_selenium(ips, config, max_workers=None):
    """Web-scrape multiple printers in parallel (one Chromium driver per thread).

    Returns {ip: result} - result as from get_web_data_with_selenium (dict/'offline'/None).
    """
    if max_workers is None:
        max_workers = config.getint('MONITORING', 'web_workers', fallback=WEB_WORKERS_DEFAULT)
    results = {}

    def _scrape_one(ip):
        driver = init_selenium_driver(config)
        if not driver:
            logging.error(f"[{ip}] Failed to initialize the Selenium driver.")
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
    """INTEGRATED function for checking toners and counters."""
    config = load_config()
    printers = [{'ip': ip_to_test}] if ip_to_test else load_printers()
    if ip_to_test: logging.info(f"Testing a single printer: {ip_to_test}")

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
        logging.warning("No printers in printers.csv. Stopping the check.")
        return

    logging.info(f"Checking toners and counters for {len(printers)} printers...")
    ip_list = [p['ip'] for p in printers if p.get('ip')]
    web_data_map = scrape_all_with_selenium(ip_list, config)

    for printer in printers:
        ip = printer['ip']
        if not ip: continue
        try:
            logging.info(f"--- Processing printer: {ip} ---")
            base_info = await get_printer_base_info(ip, community, timeout=snmp_timeout,
                                                    retries=snmp_retries, port=snmp_port)
            
            # --- Collecting toner data ---
            custom_oids = get_custom_oids_for_ip(config, ip)
            toners = await get_toner_levels_snmp(ip, community, config, custom_oids)
            
            if not toners:
                logging.warning(f"No toner data from {ip}.")
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
                        logging.info(f"[{ip}] Alert for '{toner.get('desc')}' is in cooldown. Skipping e-mail.")
            
            # --- Collecting counter data ---
            logging.info(f"[{ip}] Starting counter read...")
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
                    counter_data_row.update({'name': 'PRINTER OFFLINE (TIMEOUT)', 'status': 'OFFLINE'})
                else:
                    counter_data_row.update({'name': 'READ ERROR OCCURRED', 'status': 'ERROR'})
            all_counters_data.append(counter_data_row)
        except Exception as e:
            logging.error(f"[{ip}] Unexpected error while processing printer: {e}", exc_info=True)
            continue

    if all_toners_data_for_db: update_toner_status_in_db(all_toners_data_for_db)
    if all_counters_data: save_counter_history(all_counters_data)

    today = datetime.now().strftime("%Y-%m-%d %H:%M")

    if critical_toner_alerts:
        subject = f"[URGENT] Critical toner level ({len(critical_toner_alerts)} alerts)"
        html_body = create_html_report(critical_toner_alerts, today, "Toner", "critical")
        print_alert_summary("CRITICAL", critical_toner_alerts)
        if force_email:
            sent = send_email_notification(subject, html_body, config, 'recipient_email_toner_critical', priority='high')
            if sent:
                update_alert_timestamp(critical_toner_alerts)
    
    if low_toner_alerts:
        subject = f"[WARNING] Low toner level ({len(low_toner_alerts)} alerts)"
        html_body = create_html_report(low_toner_alerts, today, "Toner", "low")
        print_alert_summary("LOW", low_toner_alerts)
        if force_email:
            sent = send_email_notification(subject, html_body, config, 'recipient_email_toner_low')
            if sent:
                update_alert_timestamp(low_toner_alerts)

    if not critical_toner_alerts and not low_toner_alerts:
        logging.info("No new toner alerts requiring notification detected.")
    
    log_script_run('toner_check')

async def report_counters(force_email=False, ip_to_test=None):
    """
    Collects counter data, generates reports (HTML, Excel)
    and optionally sends them by e-mail. If a printer does not respond,
    the last known state from the database is used.
    """
    config = load_config()
    # Use the new function to load printers for the report
    printers = [{'ip': ip_to_test}] if ip_to_test else load_printers_for_counters()
    if not printers:
        logging.warning("No printers in printers_counters.csv. Stopping the report generation.")
        return

    if ip_to_test:
        logging.info(f"Testing the counter report for a single printer: {ip_to_test}")

    community = config.get('MONITORING', 'snmp_community', fallback='public')
    snmp_timeout = config.getint('MONITORING', 'snmp_timeout', fallback=5)
    snmp_retries = config.getint('MONITORING', 'snmp_retries', fallback=2)
    snmp_port = config.getint('MONITORING', 'snmp_port', fallback=161)
    all_counters_data = []

    logging.info(f"Collecting counter data for {len(printers)} printers...")
    ip_list = [p['ip'] for p in printers if p.get('ip')]
    web_data_map = scrape_all_with_selenium(ip_list, config)

    for printer in printers:
        ip = printer['ip']
        if not ip: continue
        try:
            logging.info(f"--- Processing counters for: {ip} ---")
            base_info = await get_printer_base_info(ip, community, timeout=snmp_timeout,
                                                    retries=snmp_retries, port=snmp_port)
            counter_data_row = {'ip': ip, **base_info}
            
            # Attempt a live read
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
                    logging.warning(f"[{ip}] Printer not responding. Looking for the last known data in the database...")
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
                            'comment': f"OFFLINE - data from {last_date}"
                        })
                        logging.info(f"[{ip}] Historical data found from {last_date}.")
                    else:
                        if web_data == 'offline':
                            counter_data_row.update({'name': 'PRINTER OFFLINE', 'status': 'OFFLINE', 'comment': 'No data in database'})
                        else:
                            counter_data_row.update({'name': 'READ ERROR', 'status': 'ERROR', 'comment': 'No data in database'})

            all_counters_data.append(counter_data_row)
        except Exception as e:
            logging.error(f"[{ip}] Unexpected error while processing counters: {e}", exc_info=True)
            continue

    if all_counters_data:
        # Zapisz tylko aktualne dane do historii
        current_data_to_save = [d for d in all_counters_data if d.get('status') == 'OK']
        if current_data_to_save:
            save_counter_history(current_data_to_save)
        
        logging.info(f"Collected data for {len(all_counters_data)} counters (including historical).")

        if force_email:
            logging.info("Forced sending the counter report by e-mail.")
            today_str = datetime.now().strftime("%Y-%m-%d")
            
            html_body = create_html_report(all_counters_data, today_str, report_type="Counters")
            excel_filename = f"Counter_Report_{today_str}.xlsx"
            excel_filepath = os.path.join(BASE_DIR, excel_filename)
            attachment_path = create_excel_report(all_counters_data, excel_filepath)

            subject = f"Printer counter report for {today_str}"
            send_email_notification(
                subject, html_body, config, 'recipient_email_counters',
                attachment_path=attachment_path
            )

            if attachment_path and os.path.exists(attachment_path):
                 os.remove(attachment_path)
                 logging.info(f"Usunieto tymczasowy plik raportu: {attachment_path}")
        else:
            logging.info("Counter data collected. Use --force-counters-email to send the report.")
    else:
        logging.warning("Failed to collect any counter data.")
        
    log_script_run('counters_report')

def create_excel_report(report_data, filename):
    if not PANDAS_AVAILABLE: return None
    df_data = []
    # Filtering removed - now all data goes into the report
    for d in report_data:
        df_data.append({
            'IP address': d.get('ip'),
            'Location': d.get('location'),
            'Name': d.get('name'),
            'Model': d.get('model'),
            'Color counter': d.get('color'),
            'B&W counter': d.get('bw'),
            'Total': d.get('sum'),
            'Notes': d.get('comment', '') # New column for notes
        })
    df = pd.DataFrame(df_data)
    # Define the column order
    df = df[['IP address', 'Location', 'Name', 'Model', 'Color counter', 'B&W counter', 'Total', 'Notes']]
    df.to_excel(filename, index=False, engine='openpyxl')
    logging.info(f"Excel report saved to: {filename}")
    return filename

def _esc(value):
    """HTML escaping for device-provided data (W6)."""
    return html.escape(str(value if value is not None else ''))


def create_html_report(report_data, today_str, report_type="Toner", alert_level="low"):
    is_toner_report = report_type == "Toner"
    
    # ... (start of the function unchanged)
    if is_toner_report:
        if alert_level == 'critical':
            title = "URGENT: Critical toner level"
            message = "<p style='text-align:center; font-size:14px;'>The following consumables require <b>immediate replacement</b>!</p>"
        else: # low
            title = "WARNING: Low toner level"
            message = "<p style='text-align:center; font-size:14px;'>Please check the stock levels and order the listed consumables.</p>"
    else:
        title = "Printer counter report"
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
    
    headers = ['IP', 'Location', 'Name', 'Model', 'Toner name', 'Level %'] if is_toner_report else ['IP', 'Location', 'Name', 'Model', 'Color', 'B&W', 'Total', 'Notes']
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
        html += f"<tr class='summary'><td colspan='4' style='text-align:right;'>TOTAL:</td><td>{total_color}</td><td>{total_bw}</td><td>{total_sum}</td><td></td></tr>"
    html += "</table></body></html>"
    return html

# --- Glowna logika programu ---
async def main():
    parser = argparse.ArgumentParser(description="Printer Monitoring.")
    parser.add_argument('--check-toner', action='store_true', help='Checks toner levels and records alerts.')
    parser.add_argument('--force-toner-email', action='store_true', help='Forces toner alert e-mails (use with --check-toner).')
    
    parser.add_argument('--report-counters', action='store_true', help='Collects counter data and generates a report.')
    parser.add_argument('--force-counters-email', action='store_true', help='Sends the generated counter report by e-mail (use with --report-counters).')

    parser.add_argument('--ip', '-i', type=str, help='Checks only a single printer with the given IP.')
    args = parser.parse_args()
    
    init_db() 

    if args.check_toner:
        # Run only the toner check with integrated data collection
        await check_toner_and_counters(args.force_toner_email, args.ip)
    elif args.report_counters:
        # Run the dedicated counter reporting function
        await report_counters(args.force_counters_email, args.ip)
    else:
        print("Choose one of the options: --check-toner or --report-counters.")
        parser.print_help()

if __name__ == "__main__":
    setup_logging()

    if not PANDAS_AVAILABLE:
        logging.warning("WARNING: 'pandas' and 'openpyxl' are not installed. Excel reports will not work.")

    if not lockfile.acquire(LOCK_FILE, max_age_seconds=3600):
        logging.error("Another monitoring process is running (active lock). Ending this run.")
        sys.exit(1)

    try:
        asyncio.run(main())
    except Exception as e:
        logging.critical(f"An unexpected error occurred: {e}")
    finally:
        lockfile.release(LOCK_FILE)
        logging.info("Lock released.")
