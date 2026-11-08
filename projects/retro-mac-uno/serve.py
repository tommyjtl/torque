#!/usr/bin/env python3
"""Serve only this release on loopback with browser isolation headers."""
import argparse
import os
import subprocess
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "www"


class Handler(SimpleHTTPRequestHandler):
    def do_POST(self):
        if (self.path != "/__shutdown" or
                self.headers.get("Origin") != f"http://localhost:{self.server.server_port}" or
                self.headers.get("X-Little-Macintosh") != "shutdown"):
            self.send_error(403)
            return
        browser = getattr(self.server, "browser", None)
        if browser is None:
            self.send_error(409)
            return
        self.send_response(204)
        self.end_headers()
        threading.Thread(target=browser.terminate, daemon=True).start()

    def end_headers(self):
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Service-Worker-Allowed", "/")
        super().end_headers()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--launch", action="store_true")
    parser.add_argument("--port", type=int, default=18791)
    parser.add_argument("--system", choices=("system-7", "mac-os-8.0", "mac-os-8.5", "beos"))
    args = parser.parse_args()
    if args.launch and not args.system:
        from choose import choose_system
        args.system = choose_system()
        if not args.system:
            raise SystemExit(0)
    if args.system == "beos":
        command = [sys.executable, str(Path(__file__).with_name("infinite_proxy.py")), "--system", "beos", "--port", str(args.port)]
        if args.launch:
            command.append("--launch")
        raise SystemExit(subprocess.call(command))
    server = ThreadingHTTPServer(("127.0.0.1", args.port), partial(Handler, directory=str(ROOT)))
    url = f"http://localhost:{args.port}/?system={args.system or 'system-7'}"
    print(f"Little Macintosh: {url}", flush=True)
    if not args.launch:
        server.serve_forever()
    else:
        profile = Path.home() / ".local/share/torque-retro-mac/chromium"
        browser = subprocess.Popen([
            "chromium", f"--user-data-dir={profile}", "--no-first-run",
            "--kiosk", url,
        ], env=os.environ.copy())
        server.browser = browser
        server.timeout = 0.5
        try:
            while browser.poll() is None:
                server.handle_request()
        finally:
            if browser.poll() is None:
                browser.terminate()
                browser.wait()
            server.server_close()
