"""The LexShift web interface: a small local server for the search demo, the evaluation view and the judging workbench.

    python -m app.server                      # http://127.0.0.1:8765
    python -m app.server --port 9000 --open   # choose a port and open the browser
    LEXSHIFT_STUBS=none python -m app.server  # every provider real (the default follows common/config.yaml)

Standard library only and offline: nothing is fetched from the network, no font, script or image is loaded from another
origin (the page's Content-Security-Policy forbids it). The server binds to the loopback address by default and checks the Host
header, so a web page you happen to have open cannot talk to it. Writes (the judging workbench) accept only JSON posted from
the page itself. When any signal comes from a fixed-value stub the page says so on every screen.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.service import Service, ServiceError  # noqa: E402

WEB = Path(__file__).resolve().parent / "web"
LOOPBACK = {"localhost", "127.0.0.1", "[::1]", "::1"}
MAX_BODY = 64 * 1024
CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; "
    "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)
MIME = {".js": "text/javascript; charset=utf-8", ".mjs": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
        ".html": "text/html; charset=utf-8", ".svg": "image/svg+xml", ".json": "application/json; charset=utf-8",
        ".woff2": "font/woff2"}


def _one(params: dict[str, list[str]], name: str, default: str | None = None) -> str | None:
    values = params.get(name)
    return values[0] if values else default


class Handler(BaseHTTPRequestHandler):
    server_version = "LexShift"
    protocol_version = "HTTP/1.1"
    server: "LexShiftServer"

    # -- plumbing ----------------------------------------------------------------------------------
    def log_message(self, fmt: str, *args: Any) -> None:
        if self.server.verbose:
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send(self, status: int, body: bytes, content_type: str, extra: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", CSP)
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, payload: Any, status: int = 200) -> None:
        self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _error(self, status: int, kind: str, message: str) -> None:
        self._json({"error": {"kind": kind, "message": message}}, status)

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").strip().lower()
        name = host.rsplit(":", 1)[0] if not host.startswith("[") else host.split("]")[0] + "]"
        return name in self.server.allowed_hosts

    def _origin_ok(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        parts = urlsplit(origin)
        host = (parts.hostname or "").lower()
        return parts.scheme in ("http", "https") and (host in self.server.allowed_hosts or f"[{host}]" in self.server.allowed_hosts)

    # -- routing -----------------------------------------------------------------------------------
    def do_HEAD(self) -> None:  # noqa: N802
        self._dispatch("GET")

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")

    def do_PUT(self) -> None:  # noqa: N802
        self._error(405, "method", "Method not allowed.")

    do_DELETE = do_PATCH = do_PUT  # noqa: N815

    def _dispatch(self, method: str) -> None:
        if not self._host_ok():
            self._error(403, "host", "Unexpected Host header: this server answers only on its own address.")
            return
        parts = urlsplit(self.path)
        path, params = parts.path, parse_qs(parts.query, keep_blank_values=True)
        try:
            if path.startswith("/api/"):
                if method == "POST":
                    self._post(path, params)
                else:
                    self._get(path, params)
            elif method == "GET":
                self._static(path)
            else:
                self._error(405, "method", "Method not allowed.")
        except ServiceError as exc:
            self._error(exc.status, exc.kind, exc.message)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:  # noqa: BLE001 - never leave a request hanging or leak a traceback to the page
            self._error(500, "internal", f"Unexpected server error ({type(exc).__name__}): {exc}")

    def _get(self, path: str, q: dict[str, list[str]]) -> None:
        s = self.server.service
        if path == "/api/status":
            self._json(s.status())
        elif path == "/api/search":
            self._json(s.search(_one(q, "q"), _one(q, "date"), _one(q, "k"), _one(q, "config", "full")))
        elif path == "/api/compare":
            self._json(s.compare(_one(q, "q"), _one(q, "date"), _one(q, "k")))
        elif path == "/api/doc":
            self._json(s.document(_one(q, "id"), _one(q, "max_chars", "60000")))
        elif path == "/api/examples":
            self._json(s.examples())
        elif path == "/api/corpus":
            self._json(s.corpus(_one(q, "n", "40")))
        elif path == "/api/evaluation":
            self._json(s.evaluation())
        elif path == "/api/judge/rounds":
            self._json(s.judge_rounds())
        elif path == "/api/judge/sheet":
            self._json(s.judge_sheet(_one(q, "round"), _one(q, "judge")))
        else:
            self._error(404, "not_found", "No such endpoint.")

    def _body(self) -> dict[str, Any]:
        if not self._origin_ok():
            raise ServiceError(403, "origin", "Cross-site request refused.")
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            raise ServiceError(415, "media_type", "Send JSON with Content-Type: application/json.")
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError as exc:
            raise ServiceError(400, "invalid", "Bad Content-Length.") from exc
        if length <= 0 or length > MAX_BODY:
            raise ServiceError(413 if length > MAX_BODY else 400, "invalid", f"The body must be between 1 and {MAX_BODY} bytes.")
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ServiceError(400, "invalid", "The body is not valid JSON.") from exc
        if not isinstance(body, dict):
            raise ServiceError(400, "invalid", "The body must be a JSON object.")
        return body

    def _post(self, path: str, _q: dict[str, list[str]]) -> None:
        body = self._body()
        if path == "/api/judge/grade":
            self._json(self.server.service.judge_grade(
                body.get("round"), body.get("judge"), body.get("qid"), body.get("doc_id"), body.get("grade"), body.get("note", ""),
            ))
        else:
            self._error(404, "not_found", "No such endpoint.")

    def _static(self, path: str) -> None:
        rel = "index.html" if path in ("", "/", "/index.html") else path.lstrip("/")
        if rel.startswith("static/"):
            rel = rel[len("static/"):]
            base = WEB / "static"
        elif rel == "index.html":
            base = WEB
        else:
            self._error(404, "not_found", "Not found.")
            return
        try:
            target = (base / rel).resolve()
            target.relative_to(base.resolve())
        except (ValueError, OSError):
            self._error(404, "not_found", "Not found.")
            return
        if not target.is_file():
            self._error(404, "not_found", "Not found.")
            return
        ctype = MIME.get(target.suffix.lower()) or mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self._send(200, target.read_bytes(), ctype)


class LexShiftServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], service: Service, verbose: bool = False) -> None:
        super().__init__(address, Handler)
        self.service = service
        self.verbose = verbose
        host = address[0].lower()
        self.allowed_hosts = set(LOOPBACK) | {host, f"[{host}]"}


def make_server(host: str = "127.0.0.1", port: int = 8765, service: Service | None = None, verbose: bool = False) -> LexShiftServer:
    return LexShiftServer((host, port), service or Service(), verbose)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.server", description=__doc__.split("\n\n")[0])
    ap.add_argument("--host", default="127.0.0.1", help="address to bind (default 127.0.0.1: this machine only)")
    ap.add_argument("--port", type=int, default=8765, help="port (default 8765; 0 picks a free one)")
    ap.add_argument("--open", action="store_true", help="open the interface in the default browser")
    ap.add_argument("--verbose", action="store_true", help="log every request")
    args = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    service = Service()
    try:
        server = make_server(args.host, args.port, service, args.verbose)
    except OSError as exc:
        print(f"Cannot listen on {args.host}:{args.port}: {exc}", file=sys.stderr)
        return 2
    url = f"http://{args.host if args.host not in ('0.0.0.0', '::') else '127.0.0.1'}:{server.server_address[1]}/"
    if args.host not in LOOPBACK:
        print(f"WARNING: bound to {args.host}: other machines can reach this server. The judging workbench can write files.",
              file=sys.stderr)
    status = service.status()
    print(f"LexShift interface at {url}")
    print("providers: " + ", ".join(f"{g}={v}" for g, v in status["providers"].items()))
    if status["load_error"]:
        print(f"WARNING: {status['load_error']}", file=sys.stderr)
    if status["stub_mode"]:
        print(f"*** STUB MODE: {', '.join(status['stubbed'])} come from fixed-value stand-ins; the page labels every result "
              "accordingly and nothing it shows is a result. ***")
    print("Press Ctrl+C to stop.")
    if args.open:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
