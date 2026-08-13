# -*- coding: utf-8 -*-
"""Toner alert triage and terminal summaries."""

import logging
from datetime import datetime, timedelta

from db import get_last_alert_timestamp


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
        location = alert.get('location', 'No location')
        name = alert.get('name', 'Brak nazwy')
        desc = alert.get('desc', 'N/A')
        level = alert.get('level', 0)

        print(f"- {ip} | {location}")
        print(f"  {name}")
        print(f"  Toner: {desc} - Level: {level:.1f}%")
        print("-" * 60)

    print(f"{'='*60}\n")


def collect_toner_alerts(ip, base_info, toners, exclude_keywords,
                              threshold_low, threshold_critical, alert_cooldown_days):
    """Triage toner readings into DB entries and low/critical alerts (with cooldown)."""
    db_entries = []
    low_alerts = []
    critical_alerts = []
    for toner in toners:
        db_entries.append({'ip': ip, **base_info, **toner})
        desc_lower = toner.get('desc', '').lower()
        if any(keyword in desc_lower for keyword in exclude_keywords):
            continue
        if 'level' not in toner:
            continue
        alert_base = {'ip': ip, **base_info, **toner}
        level = toner.get('level')
        status = toner.get('status')
        last_alert_time = get_last_alert_timestamp(ip, toner.get('desc'))
        cooldown_active = False
        if last_alert_time and (datetime.now() - last_alert_time) < timedelta(days=alert_cooldown_days):
            cooldown_active = True
        if not cooldown_active:
            if status == 'low':
                low_alerts.append(alert_base)
            elif level <= threshold_critical:
                critical_alerts.append(alert_base)
            elif level <= threshold_low:
                low_alerts.append(alert_base)
        elif status == 'low' or level <= threshold_low:
            logging.info(f"[{ip}] Alert for '{toner.get('desc')}' is in cooldown. Skipping e-mail.")
    return db_entries, low_alerts, critical_alerts
