#!/bin/bash
cd /home/admin/printer-monitor
/home/admin/printer-monitor/venv/bin/python3 main.py --report-counters --force-counters-email >> /home/admin/printer-monitor/cron.log 2>&1
