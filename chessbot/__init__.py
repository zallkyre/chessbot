"""chessbot - a difficulty-slider chess bot for your own projects.

    from chessbot import Bot
    bot = Bot(level=5)
    bot.move("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
"""

from .bot import LEVELS, PRESETS, Bot, classify, level_info, parse_level
from .engine import Engine, find_engine

__version__ = "0.2.0"
__all__ = ["Bot", "Engine", "LEVELS", "PRESETS", "level_info", "classify",
           "parse_level", "find_engine", "__version__"]
