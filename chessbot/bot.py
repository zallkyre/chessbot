"""A chess bot with a difficulty slider, and a grader for the moves you play.

    from chessbot import Bot
    bot = Bot(level=5)
    bot.move(fen)          # -> {"uci": "g1f3", "san": "Nf3", ...}
    bot.grade(fen, "g1f3") # -> {"label": "Best", "loss": 0, ...}

Levels 1-20. Low levels search less and sometimes just play a random legal
move, which is how they end up weak in a way that feels human rather than
merely slow.
"""

from __future__ import annotations

import random

import chess

from .engine import Engine

NOISE = 15          # centipawns of search noise we do not count against a move
GRADE_DEPTH = 14

# depth searched, and how often the bot plays a random legal move
LEVELS = {
    1:  {"name": "beginner", "depth": 1,  "random": 0.50},
    2:  {"name": "beginner", "depth": 1,  "random": 0.40},
    3:  {"name": "beginner", "depth": 1,  "random": 0.30},
    4:  {"name": "casual",   "depth": 2,  "random": 0.20},
    5:  {"name": "casual",   "depth": 2,  "random": 0.14},
    6:  {"name": "casual",   "depth": 2,  "random": 0.10},
    7:  {"name": "club",     "depth": 4,  "random": 0.07},
    8:  {"name": "club",     "depth": 4,  "random": 0.05},
    9:  {"name": "club",     "depth": 4,  "random": 0.04},
    10: {"name": "club",     "depth": 4,  "random": 0.03},
    11: {"name": "strong",   "depth": 7,  "random": 0.02},
    12: {"name": "strong",   "depth": 7,  "random": 0.01},
    13: {"name": "strong",   "depth": 7,  "random": 0.0},
    14: {"name": "strong",   "depth": 7,  "random": 0.0},
    15: {"name": "ruthless", "depth": 10, "random": 0.0},
    16: {"name": "ruthless", "depth": 10, "random": 0.0},
    17: {"name": "ruthless", "depth": 10, "random": 0.0},
    18: {"name": "ruthless", "depth": 13, "random": 0.0},
    19: {"name": "ruthless", "depth": 13, "random": 0.0},
    20: {"name": "ruthless", "depth": 16, "random": 0.0},
}

PRESETS = {"beginner": 2, "casual": 5, "club": 10, "strong": 14, "ruthless": 20}

LABELS = ("Best", "Excellent", "Good", "Inaccuracy", "Mistake", "Blunder")


def level_info(level: int) -> dict:
    lv = max(1, min(20, int(level)))
    info = dict(LEVELS[lv])
    info["level"] = lv
    return info


def classify(loss: int, is_best: bool) -> str:
    """Chess.com-ish labels, with a noise floor so jitter is not a mistake."""
    adjusted = max(0, loss - NOISE)
    if is_best or adjusted <= 12:
        return "Best"
    if adjusted <= 40:
        return "Excellent"
    if adjusted <= 60:
        return "Good"
    if adjusted <= 140:
        return "Inaccuracy"
    if adjusted <= 300:
        return "Mistake"
    return "Blunder"


class Bot:
    def __init__(self, level: int = 5, engine: Engine | None = None,
                 engine_path: str | None = None, seed: int | None = None):
        self.level = max(1, min(20, int(level)))
        self.engine = engine or Engine(engine_path)
        self._rng = random.Random(seed)

    # ---------------- moves ----------------
    def move(self, fen: str, level: int | None = None) -> dict:
        """Pick a move for the side to move in `fen`."""
        lv = max(1, min(20, int(level if level is not None else self.level)))
        info = LEVELS[lv]
        board = chess.Board(fen)

        if board.is_game_over():
            return {"uci": None, "san": None, "level": lv, "random": False,
                    "game_over": True, "result": board.result()}
        return self._pick(board, lv, info["depth"], info["random"])

    def _pick(self, board: chess.Board, lv: int, depth: int, chance: float) -> dict:
        chosen = None
        taken_randomly = False

        if chance and self._rng.random() < chance:
            chosen = self._rng.choice(list(board.legal_moves))
            taken_randomly = True
        else:
            uci = self.engine.search(board.fen(), lv, depth=depth)
            if uci:
                try:
                    cand = chess.Move.from_uci(uci)
                    if cand in board.legal_moves:
                        chosen = cand
                except ValueError:
                    chosen = None
            if chosen is None:
                chosen = self._rng.choice(list(board.legal_moves))

        return {
            "uci": chosen.uci(),
            "san": board.san(chosen),
            "level": lv,
            "depth": depth,
            "random": taken_randomly,
            "game_over": False,
        }

    def play(self, board: chess.Board, level: int | None = None) -> chess.Move:
        """Same thing, but takes and mutates a python-chess Board."""
        res = self.move(board.fen(), level)
        if not res["uci"]:
            raise ValueError("no legal moves")
        mv = chess.Move.from_uci(res["uci"])
        board.push(mv)
        return mv

    # ---------------- analysis ----------------
    def analyze(self, fen: str, depth: int = 14) -> dict:
        res = self.engine.analyze(fen, depth)
        res["eval"] = _fmt(res["cp"])
        return res

    def grade(self, fen: str, move: str, depth: int = GRADE_DEPTH) -> dict:
        """How good was that move? Centipawn loss against the engine's best."""
        board = chess.Board(fen)
        try:
            mv = chess.Move.from_uci(move) if len(move) in (4, 5) else board.parse_san(move)
        except ValueError:
            return {"error": "illegal move"}
        if mv not in board.legal_moves:
            return {"error": "illegal move"}

        san = board.san(mv)
        before = self.engine.analyze(fen, depth)
        board.push(mv)
        after = self.engine.analyze(board.fen(), depth)

        mover_is_white = fen.split()[1] == "w"
        before_pov = before["cp"] if mover_is_white else -before["cp"]
        after_pov = after["cp"] if mover_is_white else -after["cp"]
        loss = max(0, before_pov - after_pov)

        return {
            "san": san,
            "uci": mv.uci(),
            "loss": loss,
            "loss_pawns": round(loss / 100, 2),
            "label": classify(loss, before["best"] == mv.uci()),
            "best": before["best"],
            "eval_before": _fmt(before["cp"]),
            "eval_after": _fmt(after["cp"]),
        }

    def close(self):
        self.engine.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _fmt(cp: int) -> str:
    if abs(cp) >= 9800:
        n = round((10000 - abs(cp)) / 10)
        return ("#" if cp > 0 else "-#") + str(max(0, n))
    return f"{cp / 100:+.1f}"
