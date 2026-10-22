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
# {'san': 'f3', 'loss': 95, 'loss_pawns': 0.95, 'label': 'Inaccuracy', 'best': 'e2e4'}

bot.analyze(start, depth=14)
# {'cp': 22, 'mate': None, 'best': 'e2e4', 'eval': '+0.2'}

bot.close()
```

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
| GET | `/health` | | engine path, default level |
| GET | `/levels` | | all 20 levels + presets |
| POST | `/move` | `{"fen": "...", "level": 5}` | `{"uci","san","level","random"}` |
| POST | `/analyze` | `{"fen": "...", "depth": 14}` | `{"cp","mate","best","eval"}` |
| POST | `/grade` | `{"fen": "...", "move": "g1f3"}` | `{"label","loss","best"}` |

```bash
curl -s localhost:8787/move -H 'content-type: application/json' \
  -d '{"fen":"rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1","level":3}'
```

CORS is open, so a browser page can call it directly. It binds `127.0.0.1`
only — do not expose it to the internet as-is.

## Install

The package is not on PyPI. Clone and use it:

```powershell
git clone https://github.com/zallkyre/chessbot
cd chessbot
pip install -e .
```

You also need Stockfish, which is not bundled (98 MB):

```powershell
# official build, Windows x64
curl -L -o sf.zip https://github.com/official-stockfish/Stockfish/releases/latest/download/stockfish-windows-x86-64-universal.zip
tar -xf sf.zip
# then point at it:
$env:CHESSBOT_ENGINE = "C:\path\to\stockfish-windows-x86-64-universal.exe"
```

Lookup order: `CHESSBOT_ENGINE` → `engine/stockfish[.exe]` in the package →
`%LOCALAPPDATA%\ChessCoach\engine` → `PATH`.

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

Engine tests skip themselves if Stockfish is not installed.

## License

MIT. Stockfish is GPLv3 and is invoked as a separate process.
