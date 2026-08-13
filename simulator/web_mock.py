# -*- coding: utf-8 -*-
"""HTTP mock of printer pages for web scraping (Selenium).

Serves pages matching the layout of real devices:
- /?MAIN=DEVICE          -> frameset z ramka TopLevelFrame
- /top                   -> frameset z ramka contents
- /contents?MAIN=DEVICE  -> <div id="DeviceName">, <div id="DeviceLocation">
- /contents?MAIN=COUNTER -> <td id="TotalFullColor">, <td id="TotalBlackColor">

Offline state: serves a page WITHOUT frames -> Selenium timeout -> the 'offline' path.
"""

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SEED_FILE = os.path.join(BASE_DIR, "seed.json")
STATE_FILE = os.path.join(BASE_DIR, "state.json")

EMPTY_PAGE = b'<html><body></body></html>'


def load_seed():
    with open(SEED_FILE, encoding="utf-8") as fh:
        return json.load(fh)


def load_state():
    if not os.path.exists(STATE_FILE):
        return {}
    with open(STATE_FILE, encoding="utf-8") as fh:
        return json.load(fh)


def resolve_printer(seed_printer):
    printer = dict(seed_printer)
    printer["counters"] = dict(seed_printer.get("counters", {}))
    overrides = load_state().get(printer["ip"], {})
    if overrides.get("offline") or overrides.get("offline_web"):
        printer["offline"] = True
    if overrides.get("counters"):
        printer["counters"].update(overrides["counters"])
    return printer


def make_handler(seed_printer):
    class SimHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            printer = resolve_printer(seed_printer)
            if printer.get("offline"):
                body = EMPTY_PAGE
            else:
                body = self.render(printer)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def render(self, printer):
            path = self.path.split("?", 1)[0]
            query = self.path.split("?", 1)[1] if "?" in self.path else ""
            if path == "/":
                top_src = ("/top?" + query) if query else "/top"
                return (
                    b'<html><head></head>'
                    b'<frameset cols="100%"><frame name="TopLevelFrame" src="'
                    + top_src.encode("utf-8")
                    + b'"></frameset></html>'
                )
            if path == "/top":
                contents_src = query or "MAIN=DEVICE"
                return (
                    b'<html><head></head>'
                    b'<frameset cols="100%">'
                    b'<frame name="contents" src="/contents?' + contents_src.encode("utf-8") + b'">'
                    b'</frameset></html>'
                )
            if path == "/contents":
                if "MAIN=COUNTER" in query:
                    counters = printer.get("counters", {})
                    return (
                        '<html><body><table><tr>'
                        '<td id="TotalFullColor">%d</td>'
                        '<td id="TotalBlackColor">%d</td>'
                        '</tr></table></body></html>'
                        % (counters.get("color", 0), counters.get("bw", 0))
                    ).encode("utf-8")
                if "MAIN=DEVICE" in query:
                    return (
                        '<html><body>'
                        '<div id="DeviceName">%s</div>'
                        '<div id="DeviceLocation">%s</div>'
                        '</body></html>'
                        % (printer.get("name", ""), printer.get("location", ""))
                    ).encode("utf-8")
            return EMPTY_PAGE

        def log_message(self, format, *args):
            pass

    return SimHandler


def main():
    seed = load_seed()
    web_port = seed.get("web_port", 80)
    servers = []
    for printer in seed["printers"]:
        handler = make_handler(printer)
        server = ThreadingHTTPServer((printer["ip"], web_port), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append((printer["ip"], server, thread))
        print("WEB mock up: http://%s:%d" % (printer["ip"], web_port))
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        for _ip, server, _thread in servers:
            server.shutdown()


if __name__ == "__main__":
    main()
