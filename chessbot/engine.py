"""Talking to a Stockfish process over UCI.

No third-party dependencies. One engine, one lock, and every search is either
finished or explicitly cancelled before the next one starts, so a slow search
can never leak a stale score or move into the following request.
"""

from __future__ import annotations

import os
import queue
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

MATE_SCORE = 10000
SETTLE_TIMEOUT = 2.0        # how long we wait for a cancelled search to stop


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
        self._busy = False          # a `go` is in flight and not yet settled
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

    def _drain(self) -> int:
        """Throw away anything already sitting in the queue. Returns how many."""
        dropped = 0
        while True:
            try:
                self._q.get_nowait()
            except queue.Empty:
                return dropped
            dropped += 1

    def _recover(self):
        """Stop an unfinished search and swallow its output.

        Leaving the engine mid-search is what made the *next* request report
        the previous position's score, so this runs before every new search
        and after any search that ran out of time.
        """
        if not self._busy:
            self._drain()
            return
        self._send("stop")
        end = time.time() + SETTLE_TIMEOUT
        while time.time() < end:
            line = self._next(end - time.time())
            if line is None:
                break
            if line.startswith("bestmove"):
                break
        self._busy = False
        self._drain()

    def _run(self, fen: str, go_cmd: str, budget: float) -> dict:
        """One bounded search. Leaves the engine idle and the queue clean."""
        self._recover()

        cp, mate, best = 0, None, None
        finished = False
        self._send("position fen " + fen)
        self._busy = True
        self._send(go_cmd)

        end = time.time() + budget
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
                finished = True
                break

        if finished:
            self._busy = False
            self._drain()
        else:
            self._recover()

        return {"cp": cp, "mate": mate, "best": best, "timed_out": not finished}

    def set_skill(self, level: int):
        self._send(f"setoption name Skill Level value {max(0, min(20, int(level)))}")

    @property
    def busy(self) -> bool:
        """True while a search holds the lock."""
        return self._lock.locked()

    # ---------------- public ----------------
    def analyze(self, fen: str, depth: int = 14, timeout: float = 10.0) -> dict:
        """Score a position from White's point of view, plus the best move."""
        with self._lock:
            self.set_skill(20)          # lowered skill fuzzes the reported score
            res = self._run(fen, f"go depth {int(depth)}", timeout)
            white_to_move = fen.split()[1] == "w"
            val = _score(res["cp"], res["mate"])
            return {
                "cp": val if white_to_move else -val,
                "mate": None if res["mate"] is None else (res["mate"] if white_to_move else -res["mate"]),
                "best": res["best"],
                "timed_out": res["timed_out"],
            }

    def search(self, fen: str, level: int, depth: int | None = None,
               movetime_ms: int = 150, timeout: float | None = None) -> str | None:
        """Best move for one side at a given strength."""
        with self._lock:
            self.set_skill(level)
            if depth:
                go, budget = f"go depth {int(depth)}", (timeout or 8.0)
            else:
                go = f"go movetime {int(movetime_ms)}"
                budget = timeout or (movetime_ms / 1000 + 6)
            try:
                return self._run(fen, go, budget)["best"]
            finally:
                self.set_skill(20)

    def close(self):
        try:
            self._send("quit")
            self.proc.wait(timeout=2)
        except Exception:
            try:
                self.proc.terminate()
            except Exception:
                pass
        finally:
            for pipe in (self.proc.stdin, self.proc.stdout):
                try:
                    pipe.close()
                except Exception:
                    pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _score(cp: int, mate: int | None) -> int:
    """Fold a mate score into centipawns, from the side to move."""
    if mate is None:
        return cp
    return MATE_SCORE - abs(mate) * 10 if mate > 0 else -MATE_SCORE + abs(mate) * 10


if __name__ == "__main__":  # tiny manual check
    e = Engine()
    print(e.analyze("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", 12))
    print(e.search("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", 3))
    e.close()
