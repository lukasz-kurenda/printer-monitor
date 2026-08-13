# -*- coding: utf-8 -*-
"""Printer Monitoring - CLI orchestrator (modules: db, printers, email_utils,
alerts, snmp_client, web_scraper, reports)."""

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime

import lockfile
from common import LOCK_MAX_AGE_SECONDS, load_config, setup_logging

import db
import printers
import email_utils
import alerts
import snmp_client
import web_scraper
import reports
from db import (get_last_alert_timestamp, init_db, log_script_run, save_counter_history,
                update_alert_timestamp, update_toner_status_in_db, get_last_known_counter)
from printers import get_custom_oids_for_ip, load_printers, load_printers_for_counters
from email_utils import send_email_notification
from alerts import collect_toner_alerts, print_alert_summary
from snmp_client import (get_counters_snmp, get_printer_base_info, get_snmp_data_async,
                get_toner_levels_snmp)
from web_scraper import scrape_all_with_selenium
from reports import PANDAS_AVAILABLE, create_excel_report, create_html_report

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, 'config.ini')
LOCK_FILE = os.path.join(BASE_DIR, 'script.lock')



async def check_toner_and_counters(force_email=False, ip_to_test=None):
    """INTEGRATED function for checking toners and counters."""
    config = load_config(CONFIG_FILE)
    printers = [{'ip': ip_to_test}] if ip_to_test else load_printers()
    if ip_to_test:
        logging.info(f"Testing a single printer: {ip_to_test}")

    community = config.get('MONITORING', 'snmp_community', fallback='public')
    threshold_low = config.getint('MONITORING', 'toner_threshold_low', fallback=20)
    threshold_critical = config.getint('MONITORING', 'toner_threshold_critical', fallback=5)
    exclude_keywords = [kw.strip().lower() for kw in
                        config.get('MONITORING', 'toner_exclude_keywords', fallback='waste').split(',')]
    exclude_keywords = [k for k in exclude_keywords if k]
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
        if not ip:
            continue
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
                entries, low, critical = collect_toner_alerts(
                    ip, base_info, toners, exclude_keywords,
                    threshold_low, threshold_critical, alert_cooldown_days)
                all_toners_data_for_db.extend(entries)
                low_toner_alerts.extend(low)
                critical_toner_alerts.extend(critical)

            # --- Collecting counter data ---
            logging.info(f"[{ip}] Starting counter read...")
            counter_data_row = {'ip': ip, **base_info}
            web_data = web_data_map.get(ip)

            if web_data and web_data != 'offline':
                if not web_data.get('name'):
                    web_data['name'] = base_info.get('name')
                if not web_data.get('location'):
                    web_data['location'] = base_info.get('location')
                counter_data_row.update(web_data)
                counter_data_row['sum'] = counter_data_row.get('color', 0) + counter_data_row.get('bw', 0)
            else:
                snmp_counters = await get_counters_snmp(ip, community, custom_oids,
                                                         timeout=snmp_timeout,
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

    if all_toners_data_for_db:
        update_toner_status_in_db(all_toners_data_for_db)
    if all_counters_data:
        save_counter_history(all_counters_data)

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
    config = load_config(CONFIG_FILE)
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
        if not ip:
            continue
        try:
            logging.info(f"--- Processing counters for: {ip} ---")
            base_info = await get_printer_base_info(ip, community, timeout=snmp_timeout,
                                                    retries=snmp_retries, port=snmp_port)
            counter_data_row = {'ip': ip, **base_info}

            # Attempt a live read
            custom_oids = get_custom_oids_for_ip(config, ip)
            web_data = web_data_map.get(ip)

            if web_data and web_data != 'offline':
                if not web_data.get('name'):
                    web_data['name'] = base_info.get('name')
                if not web_data.get('location'):
                    web_data['location'] = base_info.get('location')
                counter_data_row.update(web_data)
                counter_data_row['sum'] = counter_data_row.get('color', 0) + counter_data_row.get('bw', 0)
            else:
                snmp_counters = await get_counters_snmp(ip, community, custom_oids,
                                                         timeout=snmp_timeout,
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
                            counter_data_row.update({
                                'name': 'PRINTER OFFLINE', 'status': 'OFFLINE',
                                'comment': 'No data in database'})
                        else:
                            counter_data_row.update({'name': 'READ ERROR', 'status': 'ERROR', 'comment': 'No data in database'})

            all_counters_data.append(counter_data_row)
        except Exception as e:
            logging.error(f"[{ip}] Unexpected error while processing counters: {e}", exc_info=True)
            continue

    if all_counters_data:
        # Save only current data to history
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
                 logging.info(f"Removed temporary report file: {attachment_path}")
        else:
            logging.info("Counter data collected. Use --force-counters-email to send the report.")
    else:
        logging.warning("Failed to collect any counter data.")

    log_script_run('counters_report')


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
    setup_logging(BASE_DIR, CONFIG_FILE)

    if not PANDAS_AVAILABLE:
        logging.warning("WARNING: 'pandas' and 'openpyxl' are not installed. Excel reports will not work.")

    if not lockfile.acquire(LOCK_FILE, max_age_seconds=LOCK_MAX_AGE_SECONDS):
        logging.error("Another monitoring process is running (active lock). Ending this run.")
        sys.exit(1)

    try:
        asyncio.run(main())
    except Exception as e:
        logging.critical(f"An unexpected error occurred: {e}")
    finally:
        lockfile.release(LOCK_FILE)
        logging.info("Lock released.")

