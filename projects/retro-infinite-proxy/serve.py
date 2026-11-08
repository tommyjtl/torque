#!/usr/bin/env python3
"""Experimental local cache for selected public Infinite Mac assets."""
import argparse
import hashlib
import json
import os
import subprocess
import tempfile
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlencode, urlsplit

CACHE = Path.home() / ".cache/torque-infinite-retro/v1"
SYSTEMS = {
    "beos": {"disk": "BeOS Release 3", "screenSize": "640x480", "infinite_hd": "false", "saved_hd": "false"},
    "next": {"disk": "NeXTSTEP 3.3", "infinite_hd": "false", "saved_hd": "false"},
}
MAX_FILE = 32 * 1024 * 1024


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlsplit(self.path)
        if not parsed.path.startswith(("/assets/", "/Disk/", "/embed", "/rom/", "/favicon", "/manifest", "/logo")):
            self.send_error(404)
            return
        if parsed.path == "/embed":
            data = Path(__file__).with_name("embed.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cross-Origin-Opener-Policy", "same-origin")
            self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            self.end_headers()
            self.wfile.write(data)
            return
        # Only a fixed HTTPS origin is contacted; cookies, credentials and
        # request headers are not forwarded. Distinguish query strings.
        remote = "https://www.infinitemac.org" + parsed.path + ("?" + parsed.query if parsed.query else "")
        key = hashlib.sha256(remote.encode()).hexdigest()
        CACHE.mkdir(parents=True, exist_ok=True)
        body_file, meta_file = CACHE / (key + ".data"), CACHE / (key + ".json")
        try:
            if body_file.is_file() and meta_file.is_file():
                data = body_file.read_bytes()
                content_type = json.loads(meta_file.read_text())["content_type"]
            else:
                request = urllib.request.Request(remote, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(request, timeout=35) as response:
                    content_type = response.headers.get("Content-Type", "application/octet-stream")
                    data = response.read(MAX_FILE + 1)
                if len(data) > MAX_FILE:
                    raise ValueError("upstream asset exceeds size limit")
                fd, temp_name = tempfile.mkstemp(prefix="fetch-", dir=CACHE)
                try:
                    with os.fdopen(fd, "wb") as stream:
                        stream.write(data)
                    os.replace(temp_name, body_file)
                    meta_file.write_text(json.dumps({"content_type": content_type}))
                finally:
                    if os.path.exists(temp_name):
                        os.unlink(temp_name)
        except (OSError, ValueError, urllib.error.URLError) as error:
            self.send_error(502, f"Could not retrieve emulator asset: {error}")
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        if "service-worker" in parsed.path:
            self.send_header("Service-Worker-Allowed", "/")
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--system", required=True, choices=SYSTEMS)
    parser.add_argument("--port", type=int, default=18800)
    parser.add_argument("--launch", action="store_true")
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://localhost:{args.port}/embed?{urlencode(SYSTEMS[args.system])}"
    print(url, flush=True)
    if not args.launch:
        server.serve_forever()
    else:
        profile = Path.home() / ".local/share/torque-infinite-retro" / args.system / "chromium"
        browser = subprocess.Popen(["chromium", f"--user-data-dir={profile}", "--no-first-run", "--kiosk", url])
        server.timeout = 0.5
        try:
            while browser.poll() is None:
                server.handle_request()
        finally:
            if browser.poll() is None:
                browser.terminate()
                browser.wait()
            server.server_close()
