"""Testy polityki wiązki po tacce (policies.build)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import policies
from game import Game
from generator import Generator
from pieces import PIECE_TYPES


def board_with_middle_row_one_short():
    board = 0
    for y in range(5):
        for x in range(8):
            if (x + y) % 2 == 0:
                board |= 1 << (y * 8 + x)
    for x in range(7):
        board |= 1 << (5 * 8 + x)
    return board


class LeafValueTest(unittest.TestCase):
    def test_clearing_middle_row_is_preferred(self):
        board = board_with_middle_row_one_short()
        last_cell = 1 << (5 * 8 + 7)
        cleared, lines = policies._place_and_clear(board, last_cell)
        kept = board | last_cell
        self.assertEqual(lines, 1)
        self.assertGreater(policies._value(cleared, lines), policies._value(kept, 0))


class FitProfileTest(unittest.TestCase):
    def test_single_free_cell_fits_only_one_by_one(self):
        board = ((1 << 64) - 1) & ~1
        miss, dead_types = policies._fit_profile(board)
        self.assertAlmostEqual(miss, 14 / 15)
        self.assertEqual(dead_types, 14)

    def test_miss_matches_generator_sampling(self):
        board = board_with_middle_row_one_short() | (1 << 60)
        generator = Generator(seed=7)
        samples = 20000
        misses = 0
        for _ in range(samples):
            for piece in generator.next_pieces():
                if not policies._fits(board, piece.index):
                    misses += 1
        miss, _ = policies._fit_profile(board)
        self.assertAlmostEqual(miss, misses / (3 * samples), delta=0.01)


class RiskTest(unittest.TestCase):
    def test_extremes(self):
        self.assertEqual(policies._risk(0), 0.0)
        full = (1 << 64) - 1
        self.assertAlmostEqual(
            policies._risk(full),
            policies.RISK_CUBIC + policies.RISK_LINEAR + policies.RISK_DEAD_TYPE * len(PIECE_TYPES),
        )


class LegalMovesTest(unittest.TestCase):
    def test_policy_returns_available_actions(self):
        policy = policies.build()
        for seed in (1, 2):
            game = Game(seed=seed)
            policy.reset(seed)
            while not game.done and game.placements < 40:
                actions = game.available_actions()
                if not actions:
                    break
                move = policy.act(game, actions)
                self.assertIn(move, actions)
                game.step(move)


if __name__ == "__main__":
    unittest.main()
