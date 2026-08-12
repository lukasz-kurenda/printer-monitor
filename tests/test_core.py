# -*- coding: utf-8 -*-
"""Testy jednostkowe rdzenia printer-monitor (bez sieci i Selenium)."""

import asyncio
import configparser
import sqlite3

import main


# --- Konfiguracja ---

def _monitoring_config():
    cfg = configparser.ConfigParser()
    cfg.read_dict({
        "MONITORING": {
            "toner_low_status_percent": "5",
            "toner_filter_keywords": "toner, kaseta, cartridge",
            "toner_exclude_keywords": "waste,beben,developer",
        }
    })
    return cfg


def test_load_config_reads_sections(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.ini"
    cfg_file.write_text(
        "[MONITORING]\n"
        "toner_threshold_low = 20\n"
        "snmp_community = public\n"
    )
    monkeypatch.setattr(main, "CONFIG_FILE", str(cfg_file))
    config = main.load_config()
    assert config.getint("MONITORING", "toner_threshold_low") == 20
    assert config.get("MONITORING", "snmp_community") == "public"


def test_load_config_missing_file_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "CONFIG_FILE", str(tmp_path / "nope.ini"))
    config = main.load_config()
    assert not config.sections()


# --- Listy drukarek ---

def test_load_printers_skips_blank_rows(tmp_path, monkeypatch):
    pfile = tmp_path / "printers.csv"
    pfile.write_text("192.0.2.1\n\n  \n192.0.2.2\n")
    monkeypatch.setattr(main, "PRINTERS_FILE", str(pfile))
    assert main.load_printers() == [{"ip": "192.0.2.1"}, {"ip": "192.0.2.2"}]


def test_load_printers_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "PRINTERS_FILE", str(tmp_path / "nope.csv"))
    assert main.load_printers() == []


def test_get_custom_oids_for_ip():
    config = configparser.ConfigParser()
    config.read_dict({"CUSTOM_OIDS:192.0.2.10": {"oid_color_count": "1.2.3.4.5"}})
    assert main.get_custom_oids_for_ip(config, "192.0.2.10")["oid_color_count"] == "1.2.3.4.5"
    assert main.get_custom_oids_for_ip(config, "192.0.2.11") == {}


# --- Poziomy tonerow (SNMP) ---

def test_toner_levels_percentage_mode(monkeypatch):
    async def fake_walk(ip, community, oid):
        return {"1": "Toner Black", "2": "Toner Cyan"}

    async def fake_get(ip, oids, community):
        out = {}
        for oid in oids:
            idx = oid.rsplit(".", 1)[-1]
            out[oid] = "75" if idx == "1" else "50"
        return out

    monkeypatch.setattr(main, "walk_snmp_oid", fake_walk)
    monkeypatch.setattr(main, "get_snmp_data_async", fake_get)
    custom = {
        "desc": "1.3.6.1.4.1.999.1",
        "max": "1.3.6.1.4.1.999.2",
        "current": "1.3.6.1.4.1.999.3",
        "value_is_percentage": "true",
    }
    toners = asyncio.run(main.get_toner_levels_snmp("192.0.2.1", "public", _monitoring_config(), custom))
    assert {t["desc"]: t["level"] for t in toners} == {"Toner Black": 75.0, "Toner Cyan": 50.0}


def test_toner_levels_max_mode(monkeypatch):
    async def fake_walk(ip, community, oid):
        return {"1": "Toner Black"}

    async def fake_get(ip, oids, community):
        out = {}
        for oid in oids:
            if oid.endswith(".9.1"):
                out[oid] = "7000"
            else:
                out[oid] = "10000"
        return out

    monkeypatch.setattr(main, "walk_snmp_oid", fake_walk)
    monkeypatch.setattr(main, "get_snmp_data_async", fake_get)
    toners = asyncio.run(main.get_toner_levels_snmp("192.0.2.1", "public", _monitoring_config(), None))
    assert toners[0]["level"] == 70.0
    assert toners[0]["status"] == "normal"


def test_toner_levels_special_values(monkeypatch):
    async def fake_walk(ip, community, oid):
        return {"1": "Toner Black", "2": "Toner New"}

    async def fake_get(ip, oids, community):
        out = {}
        for oid in oids:
            idx = oid.rsplit(".", 1)[-1]
            if oid.endswith(".9." + idx):
                out[oid] = {"1": "-3", "2": "0"}[idx]
            else:
                out[oid] = {"1": "10000", "2": "-2"}[idx]
        return out

    monkeypatch.setattr(main, "walk_snmp_oid", fake_walk)
    monkeypatch.setattr(main, "get_snmp_data_async", fake_get)
    toners = asyncio.run(main.get_toner_levels_snmp("192.0.2.1", "public", _monitoring_config(), None))
    by_desc = {t["desc"]: t for t in toners}
    assert by_desc["Toner Black"]["level"] == 5.0
    assert by_desc["Toner Black"]["status"] == "low"
    assert by_desc["Toner New"]["level"] == 100.0
    assert by_desc["Toner New"]["status"] == "new"


# --- Liczniki stron (SNMP, FIX-K2) ---

def test_counters_custom_oids(monkeypatch):
    async def fake_get(ip, oids, community):
        return {oids[0]: "12", oids[1]: "34"}

    monkeypatch.setattr(main, "get_snmp_data_async", fake_get)
    custom = {"oid_color_count": "1.3.6.1.4.1.999.100", "oid_bw_count": "1.3.6.1.4.1.999.101"}
    result = asyncio.run(main.get_counters_snmp("192.0.2.1", "public", "", custom))
    assert result == {"color": 12, "bw": 34, "sum": 46, "status": "OK"}


def test_counters_custom_oids_both_missing(monkeypatch):
    async def fake_get(ip, oids, community):
        return {}

    monkeypatch.setattr(main, "get_snmp_data_async", fake_get)
    custom = {"oid_color_count": "1.3.6.1.4.1.999.100", "oid_bw_count": "1.3.6.1.4.1.999.101"}
    assert asyncio.run(main.get_counters_snmp("192.0.2.1", "public", "", custom)) is None


def test_counters_fallback_total(monkeypatch):
    async def fake_get(ip, oids, community):
        return {"1.3.6.1.2.1.43.10.2.1.4.1.1": "5000"}

    monkeypatch.setattr(main, "get_snmp_data_async", fake_get)
    result = asyncio.run(main.get_counters_snmp("192.0.2.1", "public"))
    assert result == {"color": 0, "bw": 5000, "sum": 5000, "status": "OK"}


# --- Raporty HTML ---

def test_create_html_report_toner():
    data = [{"ip": "192.0.2.1", "location": "A", "name": "P1", "model": "M", "desc": "Toner Black", "level": 12.0}]
    html = main.create_html_report(data, "2026-08-12", "Toner", "low")
    assert "Niski poziom tonerów" in html
    assert "192.0.2.1" in html
    assert "12.0%" in html


def test_create_html_report_counters_summary():
    data = [{"ip": "192.0.2.1", "location": "A", "name": "P1", "model": "M",
             "color": 10, "bw": 20, "sum": 30, "status": "OK"}]
    html = main.create_html_report(data, "2026-08-12", "Counters")
    assert "SUMA:" in html
    assert "10" in html and "20" in html and "30" in html


# --- Znaczniki alertow w bazie ---

def test_alert_timestamp_roundtrip(tmp_path, monkeypatch):
    db_file = tmp_path / "printers.db"
    monkeypatch.setattr(main, "DB_FILE", str(db_file))
    con = sqlite3.connect(db_file)
    con.execute(
        "CREATE TABLE toner_status ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " ip_address TEXT NOT NULL, model TEXT, device_name TEXT, location TEXT,"
        " toner_desc TEXT NOT NULL, toner_level REAL, last_updated TEXT,"
        " alert_sent_timestamp TEXT, UNIQUE(ip_address, toner_desc))"
    )
    con.execute("INSERT INTO toner_status (ip_address, toner_desc) VALUES (?, ?)", ("192.0.2.1", "Toner Black"))
    con.commit()
    con.close()

    main.update_alert_timestamp([{"ip": "192.0.2.1", "desc": "Toner Black"}])
    assert main.get_last_alert_timestamp("192.0.2.1", "Toner Black") is not None
    assert main.get_last_alert_timestamp("192.0.2.1", "Toner Cyan") is None


# --- Wykluczenia materiałów ---

def test_exclude_keywords_filtering():
    config = _monitoring_config()
    exclude = [kw.strip().lower() for kw in config.get("MONITORING", "toner_exclude_keywords").split(",")]
    assert any(kw in "Waste Toner Box".lower() for kw in exclude)
    assert not any(kw in "Toner Black".lower() for kw in exclude)
