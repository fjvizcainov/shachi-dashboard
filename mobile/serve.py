#!/usr/bin/env python3
"""
Shachi Mobile Gateway — servidor local para acceso desde el celular.

Sirve el dashboard estático (index.html, login.html, data/*.json) y hace
proxy de /api/* hacia el servidor de trading local (localhost:5002).

PROPIEDADES DE SEGURIDAD (no las cambies sin leer docs/MOBILE-ACCESS.md):
  • Escucha SOLO en 127.0.0.1. Nunca en 0.0.0.0. Nadie en tu LAN ni en
    internet puede llegar aquí directamente.
  • La única puerta de entrada externa es `tailscale serve`, que termina
    TLS y solo acepta conexiones de dispositivos de TU tailnet (WireGuard).
  • Solo GET/HEAD. Ningún endpoint de escritura pasa por aquí.
  • Sin traversal: cualquier ruta que salga del directorio del repo → 404.

Uso:
    python3 mobile/serve.py                 # 127.0.0.1:8787
    python3 mobile/serve.py --port 9000
    SHACHI_API=http://127.0.0.1:5002 python3 mobile/serve.py
"""

import argparse
import http.client
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PORT = int(os.getenv("SHACHI_MOBILE_PORT", "8787"))
API_UPSTREAM = os.getenv("SHACHI_API", "http://127.0.0.1:5002")

# Solo estas rutas/carpetas se exponen. Todo lo demás del repo (MEMORY.md,
# bitcoin/, sync.py, .git/ ...) queda invisible para el celular.
ALLOWED_FILES = {"/", "/index.html", "/login.html", "/404.html", "/manifest.webmanifest"}
ALLOWED_DIRS = ("/data/",)

SECURITY_HEADERS = {
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(), camera=(), microphone=()",
    "Cache-Control": "no-store, max-age=0",
}


class GatewayHandler(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "ShachiMobileGateway/1.0"
    sys_version = ""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(REPO_ROOT), **kwargs)

    # ── helpers ────────────────────────────────────────────────────────────
    def _send_headers_extra(self):
        for k, v in SECURITY_HEADERS.items():
            self.send_header(k, v)

    def end_headers(self):
        self._send_headers_extra()
        super().end_headers()

    def _path_only(self):
        return urlsplit(self.path).path

    def _is_allowed(self, path):
        if path in ALLOWED_FILES:
            return True
        return any(path.startswith(d) and ".." not in path for d in ALLOWED_DIRS)

    def _deny(self, code=404):
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", "0")
        self.end_headers()

    # ── proxy /api/* → servidor de trading local ──────────────────────────
    def _proxy_api(self):
        up = urlsplit(API_UPSTREAM)
        conn_cls = http.client.HTTPSConnection if up.scheme == "https" else http.client.HTTPConnection
        try:
            conn = conn_cls(up.hostname, up.port, timeout=30)
            conn.request("GET", self.path, headers={"Host": up.netloc, "Accept": "application/json"})
            resp = conn.getresponse()
            body = resp.read()
            self.send_response(resp.status)
            ctype = resp.getheader("Content-Type", "application/json")
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command == "GET":
                self.wfile.write(body)
        except OSError as e:
            msg = ('{"error":"upstream unavailable","detail":%r}' % str(e)).encode()
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)
        finally:
            try:
                conn.close()
            except Exception:
                pass

    # ── request handlers ──────────────────────────────────────────────────
    def do_GET(self):
        path = self._path_only()
        if path.startswith("/api/"):
            return self._proxy_api()
        if path == "/healthz":
            body = b'{"status":"ok"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return self.wfile.write(body)
        if not self._is_allowed(path):
            return self._deny(404)
        return super().do_GET()

    def do_HEAD(self):
        path = self._path_only()
        if path.startswith("/api/"):
            return self._proxy_api()
        if not self._is_allowed(path):
            return self._deny(404)
        return super().do_HEAD()

    # Cualquier método que pueda mutar estado se rechaza de plano.
    def do_POST(self):    self._deny(405)
    def do_PUT(self):     self._deny(405)
    def do_DELETE(self):  self._deny(405)
    def do_PATCH(self):   self._deny(405)
    def do_OPTIONS(self): self._deny(405)

    def log_message(self, fmt, *args):
        sys.stdout.write("[gateway] %s - %s\n" % (self.address_string(), fmt % args))
        sys.stdout.flush()


def main():
    ap = argparse.ArgumentParser(description="Shachi mobile gateway (loopback only)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = ap.parse_args()

    bind = ("127.0.0.1", args.port)   # NUNCA 0.0.0.0 — ver docs/MOBILE-ACCESS.md
    httpd = ThreadingHTTPServer(bind, GatewayHandler)
    httpd.daemon_threads = True
    print(f"Shachi mobile gateway → http://{bind[0]}:{bind[1]}  (root: {REPO_ROOT})")
    print(f"API upstream           → {API_UPSTREAM}")
    print("Exponlo SOLO vía `tailscale serve`. Ctrl+C para detener.")
    sys.stdout.flush()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
