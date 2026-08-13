# -*- coding: utf-8 -*-
"""Printer list loading (CSV) and per-IP custom OIDs."""

import csv
import ipaddress
import logging
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PRINTERS_FILE = os.path.join(BASE_DIR, 'printers.csv')
PRINTERS_COUNTERS_FILE = os.path.join(BASE_DIR, 'printers_counters.csv')


def load_printers():
    """Load printers for toner monitoring and dashboard display."""
    printers = []
    try:
        with open(PRINTERS_FILE, mode='r', encoding='utf-8') as infile:
            reader = csv.reader(infile)
            for row in reader:
                if row and row[0].strip():
                    candidate = row[0].strip()
                    if candidate.startswith('#'):
                        continue  # comment / test-data marker
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
                    if candidate.startswith('#'):
                        continue  # comment / test-data marker
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
