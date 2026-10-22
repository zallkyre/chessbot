"""Basic sanity checks. Run with:  python -m unittest discover -s tests -v"""

import unittest

import chess

from chessbot import Bot, level_info
from chessbot.bot import LEVELS, classify

START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


class TestLevels(unittest.TestCase):
    def test_every_level_is_defined(self):
        self.assertEqual(sorted(LEVELS), list(range(1, 21)))

    def test_lower_levels_are_weaker(self):
        self.assertLessEqual(LEVELS[1]["depth"], LEVELS[20]["depth"])
        self.assertGreater(LEVELS[1]["random"], LEVELS[20]["random"])

    def test_level_clamped(self):
        self.assertEqual(level_info(99)["level"], 20)
        self.assertEqual(level_info(-4)["level"], 1)


class TestClassify(unittest.TestCase):
    def test_best(self):
        self.assertEqual(classify(0, True), "Best")
        self.assertEqual(classify(5, False), "Best")

    def test_labels(self):
        self.assertEqual(classify(60, False), "Good")
        self.assertEqual(classify(120, False), "Inaccuracy")
        self.assertEqual(classify(260, False), "Mistake")
        self.assertEqual(classify(900, False), "Blunder")


class TestEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.bot = Bot(level=5)
        except FileNotFoundError:
            raise unittest.SkipTest("stockfish not installed")

    @classmethod
    def tearDownClass(cls):
        cls.bot.close()

    def test_returns_a_legal_move(self):
        for _ in range(3):
            res = self.bot.move(START, level=1)
            board = chess.Board(START)
            self.assertIn(chess.Move.from_uci(res["uci"]), board.legal_moves)
            self.assertEqual(len(res["uci"]), 4)

    def test_analyze_is_white_pov(self):
        res = self.bot.analyze(START, 12)
        self.assertLess(abs(res["cp"]), 200)     # start is roughly equal

    def test_grade_flags_a_bad_move(self):
        res = self.bot.grade(START, "f2f3", depth=12)
        self.assertIn(res["label"], ("Inaccuracy", "Mistake", "Blunder"))

    def test_grade_rejects_illegal(self):
        self.assertIn("error", self.bot.grade(START, "e2e5"))


if __name__ == "__main__":
    unittest.main()
