"""python -m chessbot --serve --port 8787  |  --fen ... --level 5"""

from __future__ import annotations

import argparse
import json
import sys

from .bot import PRESETS, Bot, level_info


def main(argv=None):
    p = argparse.ArgumentParser(prog="chessbot", description="Difficulty-slider chess bot")
    p.add_argument("--serve", action="store_true", help="run the HTTP API")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8787)
    p.add_argument("--level", type=int, default=5, help="1-20, or a preset name")
    p.add_argument("--engine", default=None, help="path to stockfish")
    p.add_argument("--fen", default=None, help="print the best move for this position")
    p.add_argument("--grade", default=None, help="grade a move (uci or san) for --fen")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    args = p.parse_args(argv)

    level = args.level
    if isinstance(level, str) and level.lower() in PRESETS:
        level = PRESETS[level.lower()]

    if args.serve:
        from .server import serve

        serve(args.host, args.port, int(level), args.engine)
        return 0

    if not args.fen:
        p.print_help()
        return 2

    with Bot(level=int(level), engine_path=args.engine) as bot:
        if args.grade:
            out = bot.grade(args.fen, args.grade)
        else:
            out = bot.move(args.fen)
        if args.json:
            print(json.dumps(out, indent=2))
        else:
            if args.grade:
                print(f"{out.get('san')}  {out.get('label')}  (-{out.get('loss_pawns')} pawns)")
            else:
                print(f"{out.get('san')}  ({out.get('uci')})  level {out.get('level')} "
                      f"{level_info(out.get('level', 5))['name']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
