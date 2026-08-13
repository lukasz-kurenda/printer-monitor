# -*- coding: utf-8 -*-
"""SNMP agent simulating a fleet of printers (pysnmp 7, CommandResponder).

Answers on the OID tree that main.py queries:
- 1.3.6.1.2.1.1.5.0            sysName (name)
- 1.3.6.1.2.1.1.6.0            sysLocation (location)
- 1.3.6.1.2.1.25.3.2.1.3.1     hrDeviceDescr (model)
- 1.3.6.1.2.1.43.11.1.1.6.N    toner description
- 1.3.6.1.2.1.43.11.1.1.8.N    toner max
- 1.3.6.1.2.1.43.11.1.1.9.N    toner current
- 1.3.6.1.2.1.43.10.2.1.4.1.1  total page counter

Each printer = its own SnmpEngine + thread (transport on its own IP:161),
so the agent distinguishes devices without guessing from the packet source.
"""

import asyncio
import json
import os
import threading

from pysnmp.carrier.asyncio.dgram import udp
from pysnmp.entity import config, engine
from pysnmp.entity.rfc3413 import cmdrsp, context
from pysnmp.proto.api import v2c
from pysnmp.proto import rfc1902, rfc1905

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SEED_FILE = os.path.join(BASE_DIR, "seed.json")
STATE_FILE = os.path.join(BASE_DIR, "state.json")


def load_seed():
    with open(SEED_FILE, encoding="utf-8") as fh:
        return json.load(fh)


def load_state():
    if not os.path.exists(STATE_FILE):
        return {}
    with open(STATE_FILE, encoding="utf-8") as fh:
        return json.load(fh)


def resolve_printer(seed_printer):
    """State = seed + overrides from state.json (hot-reload on every request)."""
    printer = dict(seed_printer)
    printer["toners"] = [dict(t) for t in seed_printer.get("toners", [])]
    printer["counters"] = dict(seed_printer.get("counters", {}))
    overrides = load_state().get(printer["ip"], {})
    if overrides.get("offline"):
        printer["offline"] = True
    for toner in printer["toners"]:
        toner_over = overrides.get("toners", {}).get(toner["desc"])
        if toner_over:
            if "current" in toner_over:
                toner["current"] = toner_over["current"]
            if "max" in toner_over:
                toner["max"] = toner_over["max"]
    if overrides.get("counters"):
        printer["counters"].update(overrides["counters"])
    return printer


def build_oid_table(printer):
    """Map "1.2.3.4" -> (type, value). Types: octet|int|counter."""
    table = {
        "1.3.6.1.2.1.1.5.0": ("octet", printer.get("name", "")),
        "1.3.6.1.2.1.1.6.0": ("octet", printer.get("location", "")),
        "1.3.6.1.2.1.25.3.2.1.3.1": ("octet", printer.get("model", "")),
    }
    for idx, toner in enumerate(printer.get("toners", []), start=1):
        table["1.3.6.1.2.1.43.11.1.1.6.%d" % idx] = ("octet", toner["desc"])
        table["1.3.6.1.2.1.43.11.1.1.8.%d" % idx] = ("int", toner["max"])
        table["1.3.6.1.2.1.43.11.1.1.9.%d" % idx] = ("int", toner["current"])
    counters = printer.get("counters", {})
    total = counters.get("color", 0) + counters.get("bw", 0)
    table["1.3.6.1.2.1.43.10.2.1.4.1.1"] = ("counter", total)
    return table


def encode_value(kind, value):
    if kind == "octet":
        return v2c.OctetString(str(value))
    if kind == "counter":
        return v2c.Counter32(int(value))
    return v2c.Integer32(int(value))


def oid_tuple(oid):
    return tuple(int(part) for part in oid.split("."))


def find_next_oid(table, oid):
    """The smallest OID in the table > the given one (for GETNEXT), or None."""
    target = oid_tuple(oid)
    candidates = [oid_tuple(o) for o in table if oid_tuple(o) > target]
    if not candidates:
        return None
    return ".".join(str(part) for part in min(candidates))


class SimGetResponder(cmdrsp.GetCommandResponder):
    """Answers GET (used by get_cmd in main.py)."""

    def __init__(self, snmpEngine, contextData, printer_ip, seed_printer):
        super().__init__(snmpEngine, contextData)
        self.printer_ip = printer_ip
        self.seed_printer = seed_printer

    def handle_management_operation(self, snmpEngine, stateReference, contextName, PDU):
        printer = resolve_printer(self.seed_printer)
        if printer.get("offline"):
            return  # brak odpowiedzi -> timeout po stronie klienta
        table = build_oid_table(printer)
        var_binds = []
        for name, _value in v2c.apiPDU.get_varbinds(PDU):
            oid = str(name)
            if oid in table:
                kind, value = table[oid]
                var_binds.append((name, encode_value(kind, value)))
            else:
                var_binds.append((name, rfc1905.noSuchInstance))
        self.send_varbinds(snmpEngine, stateReference, 0, 0, var_binds)


class SimNextResponder(cmdrsp.NextCommandResponder):
    """Answers GETNEXT (used by next_cmd/walk in main.py)."""

    def __init__(self, snmpEngine, contextData, printer_ip, seed_printer):
        super().__init__(snmpEngine, contextData)
        self.printer_ip = printer_ip
        self.seed_printer = seed_printer

    def handle_management_operation(self, snmpEngine, stateReference, contextName, PDU):
        printer = resolve_printer(self.seed_printer)
        if printer.get("offline"):
            return
        table = build_oid_table(printer)
        var_binds = []
        for name, _value in v2c.apiPDU.get_varbinds(PDU):
            oid = str(name)
            next_oid = find_next_oid(table, oid)
            if next_oid is None:
                var_binds.append((name, rfc1905.endOfMibView))
            else:
                kind, value = table[next_oid]
                var_binds.append((rfc1902.ObjectName(next_oid), encode_value(kind, value)))
        self.send_varbinds(snmpEngine, stateReference, 0, 0, var_binds)


class SimBulkResponder(cmdrsp.BulkCommandResponder):
    """Minimal GETBULK handling (like GETNEXT for 1 repetition)."""

    def __init__(self, snmpEngine, contextData, printer_ip, seed_printer):
        super().__init__(snmpEngine, contextData)
        self.printer_ip = printer_ip
        self.seed_printer = seed_printer

    def handle_management_operation(self, snmpEngine, stateReference, contextName, PDU):
        printer = resolve_printer(self.seed_printer)
        if printer.get("offline"):
            return
        table = build_oid_table(printer)
        var_binds = []
        for name, _value in v2c.apiPDU.get_varbinds(PDU):
            oid = str(name)
            next_oid = find_next_oid(table, oid)
            if next_oid is None:
                var_binds.append((name, rfc1905.endOfMibView))
            else:
                kind, value = table[next_oid]
                var_binds.append((rfc1902.ObjectName(next_oid), encode_value(kind, value)))
        self.send_varbinds(snmpEngine, stateReference, 0, 0, var_binds)


def run_printer_agent(printer_ip, community, seed_printer, snmp_port):
    """Start the SNMP agent for one printer (blocking, in a thread)."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    snmp_engine = engine.SnmpEngine()
    config.add_transport(
        snmp_engine,
        udp.DOMAIN_NAME,
        udp.UdpTransport().openServerMode((printer_ip, snmp_port)),
    )
    config.add_v1_system(snmp_engine, "sim-area", community)
    config.add_vacm_user(snmp_engine, 2, "sim-area", "noAuthNoPriv", (1, 3, 6), (1, 3, 6))
    config.add_context(snmp_engine, "")
    context_data = context.SnmpContext(snmp_engine)
    SimGetResponder(snmp_engine, context_data, printer_ip, seed_printer)
    SimNextResponder(snmp_engine, context_data, printer_ip, seed_printer)
    SimBulkResponder(snmp_engine, context_data, printer_ip, seed_printer)
    snmp_engine.transportDispatcher.jobStarted(1)
    try:
        snmp_engine.transportDispatcher.runDispatcher()
    except Exception:
        import traceback
        traceback.print_exc()
        snmp_engine.transportDispatcher.closeDispatcher()
    finally:
        snmp_engine.transportDispatcher.closeDispatcher()


def main():
    seed = load_seed()
    community = seed.get("community", "public")
    snmp_port = seed.get("snmp_port", 161)
    threads = []
    for printer in seed["printers"]:
        thread = threading.Thread(
            target=run_printer_agent,
            args=(printer["ip"], community, printer, snmp_port),
            daemon=True,
            name="snmp-" + printer["ip"],
        )
        thread.start()
        threads.append(thread)
        print("SNMP agent up: %s:%d" % (printer["ip"], snmp_port))
    for thread in threads:
        thread.join()


if __name__ == "__main__":
    main()
