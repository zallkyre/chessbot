"""Talking to a Stockfish process over UCI.

No third-party dependencies. One engine, one lock, every call bounded so a
stuck search can never hang a web request.
"""

from __future__ import annotations

import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

MATE_SCORE = 10000


def find_engine() -> Path | None:
    """Where stockfish might be. First hit wins."""
    cands = []
    env = os.environ.get("CHESSBOT_ENGINE") or os.environ.get("CHESSCOACH_ENGINE")
    if env:
        cands.append(Path(env))
    here = Path(__file__).resolve().parent
    cands += [
        here / "engine" / "stockfish.exe",
        here / "engine" / "stockfish",
        here.parent / "engine" / "stockfish.exe",
        Path.cwd() / "engine" / "stockfish.exe",
        Path.cwd() / "engine" / "stockfish",
    ]
    if os.name == "nt":
        cands.append(Path(os.environ.get("LOCALAPPDATA", "")) / "ChessCoach" / "engine" / "stockfish.exe")
    for c in cands:
        try:
            if c.is_file() and c.stat().st_size > 100_000:
                return c
        except OSError:
            pass
    for name in ("stockfish", "stockfish.exe"):
        found = shutil.which(name)
        if found:
            return Path(found)
    return None


class Engine:
    def __init__(self, path: Path | str | None = None, threads: int = 2, hash_mb: int = 64):
        self.path = Path(path) if path else find_engine()
        if not self.path or not Path(self.path).exists():
            raise FileNotFoundError(
                "Stockfish not found. Set CHESSBOT_ENGINE, or drop stockfish.exe "
                "next to the package. Official builds: "
                "https://github.com/official-stockfish/Stockfish/releases"
            )
        kwargs = {}
        if os.name == "nt":
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            kwargs["startupinfo"] = si
            kwargs["creationflags"] = 0x08000000
        self.proc = subprocess.Popen(
            [str(self.path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            **kwargs,
        )
        self._q: queue.Queue[str] = queue.Queue()
        self._lock = threading.Lock()
        threading.Thread(target=self._read, daemon=True).start()

        self._send("uci")
        self._wait(lambda l: l == "uciok", 10)
        self._send(f"setoption name Threads value {threads}")
        self._send(f"setoption name Hash value {hash_mb}")
        self._send("setoption name Ponder value false")
        self._send("isready")
        self._wait(lambda l: l == "readyok", 10)
        self.set_skill(20)

    # ---------------- plumbing ----------------
    def _read(self):
        try:
            for line in self.proc.stdout:
                self._q.put(line.strip())
        except Exception:
            pass

    def _send(self, cmd: str):
        try:
            self.proc.stdin.write(cmd + "\n")
            self.proc.stdin.flush()
        except Exception:
            pass

    def _next(self, timeout: float):
        try:
            return self._q.get(timeout=max(0.01, timeout))
        except queue.Empty:
            return None

    def _wait(self, pred, timeout: float):
        end = time.time() + timeout
        while time.time() < end:
            line = self._next(end - time.time())
            if line is None:
                return None
            if pred(line):
                return line
        return None

    def set_skill(self, level: int):
        self._send(f"setoption name Skill Level value {max(0, min(20, int(level)))}")

    # ---------------- public ----------------
    def analyze(self, fen: str, depth: int = 14, timeout: float = 10.0) -> dict:
        """Score a position from White's point of view, plus the best move."""
        with self._lock:
            cp, mate, best = 0, None, None
            self.set_skill(20)          # lowered skill fuzzes the reported score
            self._send("position fen " + fen)
            self._send(f"go depth {int(depth)}")
            end = time.time() + timeout
            while time.time() < end:
                line = self._next(end - time.time())
                if line is None:
                    break
                if line.startswith("info"):
                    m = re.search(r"score (cp|mate) (-?\d+)", line)
                    if m:
                        if m.group(1) == "cp":
                            cp, mate = int(m.group(2)), None
                        else:
                            mate = int(m.group(2))
                elif line.startswith("bestmove"):
                    parts = line.split()
                    best = parts[1] if len(parts) > 1 and parts[1] != "(none)" else None
                    break
            if mate is not None:
                val = MATE_SCORE - abs(mate) * 10 if mate > 0 else -MATE_SCORE + abs(mate) * 10
            else:
                val = cp
            white = val if fen.split()[1] == "w" else -val
            return {"cp": white, "mate": mate, "best": best}

    def search(self, fen: str, level: int, depth: int | None = None,
               movetime_ms: int = 150, timeout: float | None = None) -> str | None:
        """Best move for one side at a given strength."""
        with self._lock:
            best = None
            self.set_skill(level)
            self._send("position fen " + fen)
            if depth:
                self._send(f"go depth {int(depth)}")
                budget = timeout or 8.0
            else:
                self._send(f"go movetime {int(movetime_ms)}")
                budget = timeout or (movetime_ms / 1000 + 6)
            end = time.time() + budget
            while time.time() < end:
                line = self._next(end - time.time())
                if line is None:
                    break
                if line.startswith("bestmove"):
                    parts = line.split()
                    best = parts[1] if len(parts) > 1 and parts[1] != "(none)" else None
                    break
            self.set_skill(20)
            return best

    def close(self):
        try:
            self._send("quit")
            self.proc.terminate()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


if __name__ == "__main__":  # tiny manual check
    e = Engine()
    print(e.analyze("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", 12))
    print(e.search("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", 3))
    e.close()
