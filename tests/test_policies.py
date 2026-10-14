"""
Testy polityki tacki: kontrakt build/reset/act i pomocnicze operacje na bitboardzie.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game import Game
from policies import FULL, _bits, _clear, _isolated, _risk, _transitions, build


class TestTrayPolicyContract(unittest.TestCase):
    def test_build_accepts_missing_weights(self):
        policy = build(None)
        policy.reset(1)
        game = Game(seed=1)
        actions = game.available_actions()
        self.assertIn(policy.act(game, actions), actions)

    def test_plays_only_legal_moves(self):
        policy = build(None)
        for seed in (3, 11):
            game = Game(seed=seed)
            policy.reset(seed)
            for _ in range(60):
                actions = game.available_actions()
                if game.done or not actions:
                    break
                move = policy.act(game, actions)
                self.assertIn(move, actions)
                game.step(move)
            self.assertGreater(game.placements, 0)


class TestBitboardHelpers(unittest.TestCase):
    def test_full_row_is_cleared(self):
        grid = [[1] * 8] + [[0] * 8 for _ in range(7)]
        board, cleared = _clear(_bits(grid))
        self.assertEqual((board, cleared), (0, 1))

    def test_empty_board_has_no_transitions(self):
        self.assertEqual(_transitions(0), 0)

    def test_single_cell_adds_four_transitions(self):
        center = 1 << (8 * 3 + 3)
        self.assertEqual(_transitions(center), 4)

    def test_enclosed_empty_cell_is_isolated(self):
        corner_enclosed = (1 << 1) | (1 << 8)
        self.assertEqual(_isolated(corner_enclosed), 1)

    def test_risk_is_zero_when_every_piece_fits(self):
        self.assertEqual(_risk(0), 0.0)

    def test_risk_is_one_when_no_piece_fits(self):
        self.assertAlmostEqual(_risk(FULL), 1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
