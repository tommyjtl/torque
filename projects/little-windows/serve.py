#!/usr/bin/env python3
"""Local-only v86 server with a bounded-URL, on-demand disk-part cache."""
import argparse
import os
import re
import subprocess
import tempfile
import urllib.error
import urllib.request
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent / "www"
CACHE = Path.home() / ".cache/little-windows/v86-images-v1"
PART = re.compile(r"^/images/(windows95-v3)/(\d+)-(\d+)\.img$")
SIZES = {"windows95-v3": 471859200}
CHUNK = 262144


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        path = urlsplit(self.path).path
        match = PART.fullmatch(path)
        if not match:
            return super().do_GET()
        disk, start_text, end_text = match.groups()
        start, end = int(start_text), int(end_text)
        if start % CHUNK or end != start + CHUNK or end > SIZES[disk]:
            self.send_error(400)
            return
        folder = CACHE / disk
        folder.mkdir(parents=True, exist_ok=True)
        name = f"{start}-{end}.img"
        file = folder / name
        try:
            if not file.is_file() or file.stat().st_size != CHUNK:
                with urllib.request.urlopen(f"https://i.copy.sh/{disk}/{name}", timeout=30) as response:
                    data = response.read(CHUNK + 1)
                if len(data) != CHUNK:
                    raise ValueError("Unexpected disk part size")
                fd, temp_name = tempfile.mkstemp(prefix="part-", dir=folder)
                try:
                    with os.fdopen(fd, "wb") as temp:
                        temp.write(data)
                    os.replace(temp_name, file)
                finally:
                    if os.path.exists(temp_name):
                        os.unlink(temp_name)
            data = file.read_bytes()
        except (OSError, ValueError, urllib.error.URLError) as error:
            self.send_error(502, f"Could not retrieve Windows disk part: {error}")
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def end_headers(self):
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        super().end_headers()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--launch", action="store_true")
    parser.add_argument("--port", type=int, default=18794)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), partial(Handler, directory=str(ROOT)))
    url = f"http://localhost:{args.port}/"
    print(f"Little Windows: {url}", flush=True)
    if not args.launch:
        server.serve_forever()
    else:
        profile = Path.home() / ".local/share/torque-little-windows/chromium"
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
