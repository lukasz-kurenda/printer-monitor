# -*- coding: utf-8 -*-
"""SQLite persistence layer for printer-monitor (DRY refactor)."""

import logging
import sqlite3
from datetime import datetime, timedelta

DB_FILE = None  # set at import time below
import os
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, 'printers.db')


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
        logging.error("Failed to update alert timestamps in the database: %s", e)


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
        con.row_factory = sqlite3.Row  # Enables column access by name
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
