"""Basic sanity checks. Run with:  python -m unittest discover -s tests -v"""

import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import chess

from chessbot import Bot, level_info, parse_level
from chessbot.bot import LEVELS, PRESETS, classify

START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
# White to move and Ra8 is mate. h2h3 is the control: it misses mate.
MATE1 = "6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1"
# Mirrored: Black to move and Ra1 is mate.
BLACK_MATES = "r5k1/5ppp/8/8/8/8/5PPP/6K1 b - - 0 1"
COMPLEX = "r1bq1rk1/pp2bppp/2n1pn2/3p4/2PP4/2N1PN2/PP1B1PPP/R2QKB1R w KQ - 0 10"


class TestLevels(unittest.TestCase):
    def test_every_level_is_defined(self):
        self.assertEqual(sorted(LEVELS), list(range(1, 21)))

    def test_lower_levels_are_weaker(self):
        self.assertLessEqual(LEVELS[1]["depth"], LEVELS[20]["depth"])
        self.assertGreater(LEVELS[1]["random"], LEVELS[20]["random"])

    def test_level_clamped(self):
        self.assertEqual(level_info(99)["level"], 20)
        self.assertEqual(level_info(-4)["level"], 1)

    def test_preset_names_parse(self):
        for name, lv in PRESETS.items():
            self.assertEqual(parse_level(name), lv)
            self.assertEqual(parse_level(name.upper()), lv)

    def test_numeric_strings_parse(self):
        self.assertEqual(parse_level("7"), 7)
        self.assertEqual(parse_level(" 12 "), 12)

    def test_unknown_preset_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_level("grandmaster")


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
        self.assertFalse(res["timed_out"])

    def test_analyze_mate_is_white_pov_for_both_sides(self):
        white_mates = self.bot.analyze(MATE1, 12)
        self.assertEqual(white_mates["mate"], 1)
        self.assertGreater(white_mates["cp"], 0)
        # black delivers mate here: `mate` and `cp` must agree that White is lost.
        # Before the fix these disagreed whenever Black was to move.
        stm = self.bot.analyze(BLACK_MATES, 12)
        self.assertEqual(stm["mate"], -1)
        self.assertLess(stm["cp"], 0)

    def test_grade_rewards_black_delivering_mate(self):
        res = self.bot.grade(BLACK_MATES, "a8a1", depth=12)
        self.assertEqual(res["label"], "Best")
        self.assertEqual(res["loss"], 0)

    def test_grade_rewards_delivering_mate(self):
        res = self.bot.grade(MATE1, "a1a8", depth=12)
        self.assertEqual(res["label"], "Best")
        self.assertEqual(res["loss"], 0)

    def test_grade_punishes_missing_mate(self):
        res = self.bot.grade(MATE1, "h2h3", depth=12)
        self.assertEqual(res["label"], "Blunder")
        self.assertLessEqual(res["loss_pawns"], 20.0)   # capped, never -100

    def test_grade_rejects_illegal(self):
        self.assertIn("error", self.bot.grade(START, "e2e5"))

    def test_timeout_does_not_leak_into_next_analyze(self):
        """Regression: a cancelled search used to poison the following call."""
        self.bot.engine.analyze(COMPLEX, depth=40, timeout=0.05)
        res = self.bot.engine.analyze(START, depth=8, timeout=10)
        self.assertFalse(res["timed_out"])
        self.assertLess(abs(res["cp"]), 100)          # not COMPLEX's score
        self.assertIsNotNone(res["best"])             # before the fix: None
        self.assertIn(chess.Move.from_uci(res["best"]), chess.Board(START).legal_moves)

    def test_timeout_does_not_leak_into_next_search(self):
        self.bot.engine.search(COMPLEX, 20, depth=40, timeout=0.05)
        mv = self.bot.engine.search(START, 20, depth=1, timeout=5)
        self.assertIsNotNone(mv)                      # before the fix: None
        self.assertIn(chess.Move.from_uci(mv), chess.Board(START).legal_moves)


class TestServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from chessbot.server import Handler

        try:
            cls.bot = Bot(level=3)
        except FileNotFoundError:
            raise unittest.SkipTest("stockfish not installed")
        Handler.bot = cls.bot
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_port}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.bot.close()

    def _post(self, path, payload):
        req = urllib.request.Request(
            self.base + path,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as exc:
            try:
                return exc.code, json.loads(exc.read())
            finally:
                exc.close()

    def test_health(self):
        with urllib.request.urlopen(self.base + "/health", timeout=10) as r:
            self.assertEqual(r.status, 200)
            self.assertTrue(json.loads(r.read())["ok"])

    def test_cors_preflight(self):
        req = urllib.request.Request(self.base + "/move", method="OPTIONS")
        with urllib.request.urlopen(req, timeout=10) as r:
            self.assertEqual(r.status, 204)
            self.assertEqual(r.headers["Access-Control-Allow-Origin"], "*")

    def test_move_accepts_a_preset_level(self):
        status, body = self._post("/move", {"fen": START, "level": "casual"})
        self.assertEqual(status, 200)
        self.assertIn(chess.Move.from_uci(body["uci"]), chess.Board(START).legal_moves)

    def test_bad_input_is_400_not_500(self):
        self.assertEqual(self._post("/move", {"fen": START, "level": "nuts"})[0], 400)
        self.assertEqual(self._post("/move", {"fen": "not a fen"})[0], 400)
        self.assertEqual(self._post("/analyze", {"fen": START, "depth": "abc"})[0], 400)
        self.assertEqual(self._post("/grade", {"fen": START, "move": "e2e5"})[0], 400)


if __name__ == "__main__":
    unittest.main()
