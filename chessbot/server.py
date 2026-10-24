"""Tiny HTTP API over the bot. Stdlib only, no framework to install.

    python -m chessbot --serve --port 8787

    GET  /health
    GET  /levels
    POST /move     {"fen": "...", "level": 5}      -> {"uci","san","level",...}
    POST /analyze  {"fen": "...", "depth": 14}     -> {"cp","mate","best","eval"}
    POST /grade    {"fen": "...", "move": "g1f3"}  -> {"label","loss",...}

Bad input is a 400, not a 500. Long jobs that would queue behind a running
search get a 503 and a Retry-After instead of piling up on the engine lock.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import chess

from .bot import LEVELS, PRESETS, Bot, level_info, parse_level

MAX_BODY = 64 * 1024
GRADE_DEPTH = 10


class Handler(BaseHTTPRequestHandler):
    bot: Bot | None = None
    server_version = "chessbot/0.1"

    # ---------------- helpers ----------------
    def _send(self, code: int, payload: dict, headers: dict | None = None):
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Access-Control-Allow-Origin", "*")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(raw)

    def _busy(self) -> bool:
        if self.bot and self.bot.engine.busy:
            return True
        return False

    def _body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return {}
        if length <= 0 or length > MAX_BODY:
            return {}
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}
        return body if isinstance(body, dict) else {}

    def _fen(self, body: dict) -> str | None:
        fen = (body.get("fen") or "").strip()
        if not fen:
            return None
        try:
            chess.Board(fen[:200])
            return fen[:200]
        except ValueError:
            return None

    def _int(self, body: dict, key: str, default: int, lo: int, hi: int) -> int | None:
        """None means the caller sent junk, which is a 400."""
        raw = body.get(key, default)
        try:
            return max(lo, min(hi, int(raw)))
        except (TypeError, ValueError):
            return None

    def _level(self, body: dict) -> int | None:
        raw = body.get("level", self.bot.level)
        try:
            return parse_level(raw)
        except (TypeError, ValueError):
            return None

    def log_message(self, fmt, *args):     # quiet by default
        pass

    # ---------------- routes ----------------
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "86400")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if self.path.startswith("/health"):
            return self._send(200, {"ok": True, "engine": str(self.bot.engine.path),
                                    "level": self.bot.level,
                                    "busy": self._busy()})
        if self.path.startswith("/levels"):
            return self._send(200, {"presets": PRESETS, "levels": {
                str(k): {**v, "level": k} for k, v in LEVELS.items()}})
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        body = self._body()

        if self.path.startswith("/move"):
            fen = self._fen(body)
            if not fen:
                return self._send(400, {"error": "fen required and must be legal"})
            level = self._level(body)
            if level is None:
                return self._send(400, {"error": "level must be 1-20 or a preset name"})
            try:
                return self._send(200, self.bot.move(fen, level))
            except Exception as exc:
                return self._send(500, {"error": f"{type(exc).__name__}: {exc}"})

        if self.path.startswith("/analyze"):
            fen = self._fen(body)
            if not fen:
                return self._send(400, {"error": "fen required and must be legal"})
            depth = self._int(body, "depth", 14, 1, 30)
            if depth is None:
                return self._send(400, {"error": "depth must be an integer 1-30"})
            if self._busy():
                return self._send(503, {"error": "engine busy, retry shortly"},
                                  {"Retry-After": "1"})
            try:
                return self._send(200, self.bot.analyze(fen, depth))
            except Exception as exc:
                return self._send(500, {"error": f"{type(exc).__name__}: {exc}"})

        if self.path.startswith("/grade"):
            fen = self._fen(body)
            move = (body.get("move") or "").strip()
            if not fen or not move:
                return self._send(400, {"error": "fen and move required"})
            depth = self._int(body, "depth", GRADE_DEPTH, 1, 24)
            if depth is None:
                return self._send(400, {"error": "depth must be an integer 1-24"})
            if self._busy():
                return self._send(503, {"error": "engine busy, retry shortly"},
                                  {"Retry-After": "1"})
            try:
                out = self.bot.grade(fen, move, depth)
            except Exception as exc:
                return self._send(500, {"error": f"{type(exc).__name__}: {exc}"})
            return self._send(400 if "error" in out else 200, out)

        return self._send(404, {"error": "not found"})


def serve(host: str = "127.0.0.1", port: int = 8787, level: int | str = 5,
          engine_path: str | None = None):
    bot = Bot(level=level, engine_path=engine_path)
    Handler.bot = bot
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"chessbot  http://{host}:{port}")
    print(f"  engine {bot.engine.path}")
    print(f"  level  {bot.level}  ({level_info(bot.level)['name']})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        bot.close()
