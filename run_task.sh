#!/bin/bash
# Przejdz do katalogu, w ktorym znajduje sie skrypt
cd "$(dirname "$0")"

# Uruchom skrypt Pythona z odpowiednia flaga i zapisz logi
/home/admin/printer-monitor/venv/bin/python3 main.py $1 >> /home/admin/printer-monitor/cron.log 2>&1
