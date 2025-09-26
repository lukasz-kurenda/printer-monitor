#!/bin/bash
echo "$(date): Skrypt check_toners.sh uruchomiony przez cron" >> /home/admin/logs/printer-monitor.log
cd /home/admin/printer-monitor
/home/admin/printer-monitor/venv/bin/python3 main.py --check-toner --force-toner-email >> /home/admin/printer-monitor/cron.log 2>&1
