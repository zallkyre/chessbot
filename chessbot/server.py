"""Tiny HTTP API over the bot. Stdlib only, no framework to install.

    python -m chessbot --serve --port 8787

    GET  /health
    GET  /levels
    POST /move     {"fen": "...", "level": 5}      -> {"uci","san","level",...}
    POST /analyze  {"fen": "...", "depth": 14}     -> {"cp","mate","best","eval"}
    POST /grade    {"fen": "...", "move": "g1f3"}  -> {"label","loss",...}
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import chess

from .bot import LEVELS, PRESETS, Bot, level_info

MAX_BODY = 64 * 1024


class Handler(BaseHTTPRequestHandler):
    bot: Bot | None = None
    server_version = "chessbot/0.1"

    # ---------------- helpers ----------------
    def _send(self, code: int, payload: dict):
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(raw)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY:
            return {}
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return {}

    def _fen(self, body: dict) -> str | None:
        fen = (body.get("fen") or "").strip()
        if not fen:
            return None
        try:
            chess.Board(fen[:200])
            return fen[:200]
        except ValueError:
            return None

    def log_message(self, fmt, *args):     # quiet by default
        pass

    # ---------------- routes ----------------
    def do_GET(self):
        if self.path.startswith("/health"):
            return self._send(200, {"ok": True, "engine": str(self.bot.engine.path),
                                    "level": self.bot.level})
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
            level = body.get("level", self.bot.level)
            try:
                return self._send(200, self.bot.move(fen, level))
            except Exception as exc:
                return self._send(500, {"error": f"{type(exc).__name__}: {exc}"})

        if self.path.startswith("/analyze"):
            fen = self._fen(body)
            if not fen:
                return self._send(400, {"error": "fen required and must be legal"})
            depth = max(1, min(30, int(body.get("depth", 14))))
            try:
                return self._send(200, self.bot.analyze(fen, depth))
            except Exception as exc:
                return self._send(500, {"error": f"{type(exc).__name__}: {exc}"})

        if self.path.startswith("/grade"):
            fen = self._fen(body)
            move = (body.get("move") or "").strip()
            if not fen or not move:
                return self._send(400, {"error": "fen and move required"})
            depth = max(1, min(24, int(body.get("depth", 14))))
            try:
                return self._send(200, self.bot.grade(fen, move, depth))
            except Exception as exc:
                return self._send(500, {"error": f"{type(exc).__name__}: {exc}"})

        return self._send(404, {"error": "not found"})


def serve(host: str = "127.0.0.1", port: int = 8787, level: int = 5,
          engine_path: str | None = None):
    bot = Bot(level=level, engine_path=engine_path)
    Handler.bot = bot
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"chessbot  http://{host}:{port}")
    print(f"  engine {bot.engine.path}")
    print(f"  level  {level}  ({level_info(level)['name']})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        bot.close()
