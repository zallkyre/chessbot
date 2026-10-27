# chessbot

A difficulty-slider chess bot and a move grader, in one small package.

Built for reuse: give it a FEN, get a legal move at level 1-20. Or give it a
position and a move, and it tells you how much that move cost.

Stockfish does the searching. The difficulty model is the part that matters.

```
pip install chessbot          # (not on PyPI yet - see Install)
```

## Why the slider actually works

Stockfish's `Skill Level` only widens move selection. On its own, "level 1" is
still roughly a 1200 player, which is not beginner-friendly.

So each level changes two things:

| levels | name | search depth | chance of a random legal move |
|---|---|---|---|
| 1 | beginner | 1 ply | 50% |
| 2-3 | beginner | 1 ply | 40 / 30% |
| 4-6 | casual | 2 ply | 20 / 14 / 10% |
| 7-10 | club | 4 ply | 7 / 5 / 4 / 3% |
| 11-14 | strong | 7 ply | 2 / 1 / 0 / 0% |
| 15-20 | ruthless | 10-16 ply | none |

At level 1 the bot genuinely hangs pieces. At level 20 it does not.

## Python

```python
from chessbot import Bot

bot = Bot(level=5)                      # or Bot(level="casual")
start = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

bot.move(start)
# {'uci': 'g1f3', 'san': 'Nf3', 'level': 5, 'depth': 2, 'random': False, ...}

bot.grade(start, "f2f3")
# {'san': 'f3', 'loss': 104, 'loss_pawns': 1.04, 'label': 'Inaccuracy',
#  'best': 'e2e4', 'mate_before': None, 'mate_after': None, ...}

bot.analyze(start, depth=14)
# {'cp': 30, 'mate': None, 'best': 'e2e4', 'timed_out': False, 'eval': '+0.3'}

bot.close()
```

`level` accepts an int 1-20, a numeric string, or a preset name
(`beginner`, `casual`, `club`, `strong`, `ruthless`) anywhere a level appears:
the constructor, `move()`, `--level`, and the JSON body of `POST /move`.

Both `cp` and `mate` are from **White's** point of view, so they never
disagree about who is winning. `loss_pawns` is capped at 20.0 so a missed mate
reads `-20.0`, not `-100.0`.

With `python-chess` boards:

```python
import chess
board = chess.Board()
bot.play(board, level=8)     # pushes the move for you
```

## HTTP

```powershell
python -m chessbot --serve --port 8787
```

| method | path | body | returns |
|---|---|---|---|
| GET | `/health` | | engine path, default level, `busy` |
| GET | `/levels` | | all 20 levels + presets |
| POST | `/move` | `{"fen": "...", "level": 5}` | `{"uci","san","level","random"}` |
| POST | `/analyze` | `{"fen": "...", "depth": 14}` | `{"cp","mate","best","eval"}` |
| POST | `/grade` | `{"fen": "...", "move": "g1f3", "depth": 10}` | `{"label","loss","best"}` |

Bad input is a `400` with a message, not a `500`. `OPTIONS` is answered, so a
browser page can `POST` JSON across origins. `/analyze` and `/grade` return
`503` with `Retry-After` while a search is already running, instead of queueing
behind the engine lock.

```bash
curl -s localhost:8787/move -H 'content-type: application/json' \
  -d '{"fen":"rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1","level":"club"}'
```

CORS is open, so a browser page can call it directly. It binds `127.0.0.1`
only — do not expose it to the internet as-is.

## Install

```powershell
pip install "git+https://github.com/zallkyre/chessbot@v0.2.0"
```

Pin the tag, or drop `@v0.2.0` for whatever `main` is that day. Not on PyPI.

Then point it at Stockfish, which is not bundled (98 MB):

```powershell
# official build, Windows x64
curl -L -o sf.zip https://github.com/official-stockfish/Stockfish/releases/latest/download/stockfish-windows-x86-64-universal.zip
tar -xf sf.zip
$env:CHESSBOT_ENGINE = "C:\path\to\stockfish-windows-x86-64-universal.exe"
```

Lookup order: `CHESSBOT_ENGINE` → `engine/stockfish[.exe]` in the package →
`%LOCALAPPDATA%\ChessCoach\engine` → `PATH`.

Working on the package itself:

```powershell
git clone https://github.com/zallkyre/chessbot
cd chessbot
pip install -e .
```

## Grading

`grade()` is the same model the [Chess Coach](https://github.com/zallkyre/chess-coach)
app uses: centipawn loss against the engine's best move, minus a 15cp search-noise
floor, then labelled Best / Excellent / Good / Inaccuracy / Mistake / Blunder.

The noise floor is the important bit. Without it, two shallow searches disagree by
0.2 pawns and every other move looks like a mistake.

## Tests

```powershell
python -m unittest discover -s tests -v
```

Engine tests skip themselves if Stockfish is not installed. CI (`.github/workflows/tests.yml`)
runs the suite on Linux (Python 3.10 and 3.13) and Windows with Stockfish
installed.

Two of those tests are regressions for a real bug: a search that ran out of
time used to leave Stockfish mid-search, and the *next* request would report
the previous position's score. Every search is now either finished or
cancelled with `stop` and drained before the next one starts.

## Changelog

### 0.2.0

- Fixed: a search that hit its deadline left Stockfish running, so the next
  request reported the previous position's score and could consume a stale
  `bestmove`. Searches are now cancelled and drained first; results carry
  `timed_out`.
- Preset level names (`beginner`, `casual`, `club`, `strong`, `ruthless`) work
  in `Bot()`, `--level`, and `POST /move`.
- `analyze()` reports `mate` from White's point of view, matching `cp`.
- `grade()` handles checkmate and stalemate, refuses timed-out scores, and caps
  `loss_pawns` at 20.0.
- HTTP: `400` for bad input, `OPTIONS` preflight answered, `503` while the
  engine is busy, `/grade` defaults to depth 10.
- Added `LICENSE`, CI on Linux and Windows, and PyPI-ready packaging metadata.

### 0.1.0

- First release: 20-level difficulty slider and centipawn-loss move grading.

## License

MIT — see [LICENSE](LICENSE). Stockfish is GPLv3 and is invoked as a separate process.

---

**LLM guide** — Difficulty-slider chess bot and move grader built on Stockfish · Stack: Python · Run: `pip install .` · License: MIT
