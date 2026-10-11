import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from board import Board
from game import Game
from pieces import PIECE_POOL, PIECE_TYPES
from policies import build
import survival


def random_board(rng):
    board = Board()
    for r in range(8):
        for c in range(8):
            board.grid[r][c] = 1 if rng.random() < 0.45 else 0
    return board


class SurvivalModelTest(unittest.TestCase):
    def test_bit_clear_matches_board(self):
        rng = random.Random(1)
        for _ in range(300):
            board = random_board(rng)
            occ = survival.board_bits(board.grid)
            rows, cols = board.check_full_lines()
            board.clear_lines(rows, cols)
            after, lines = survival.clear_lines(occ)
            self.assertEqual(lines, len(rows) + len(cols))
            self.assertEqual(survival.board_bits(board.grid), after)

    def test_placements_match_board(self):
        rng = random.Random(2)
        for _ in range(200):
            board = random_board(rng)
            occ = survival.board_bits(board.grid)
            for pose, piece in enumerate(PIECE_POOL):
                fits = {mask for mask in survival.PLACEMENTS[pose] if not occ & mask}
                expected = set()
                for y in range(8 - len(piece.shape) + 1):
                    for x in range(8 - len(piece.shape[0]) + 1):
                        if board.can_place_piece(piece, x, y):
                            expected.add(survival.POSE_BITS[pose] << (y * 8 + x))
                self.assertEqual(fits, expected)

    def test_holes_match_brute_force(self):
        rng = random.Random(4)
        for _ in range(300):
            board = random_board(rng)
            expected = 0
            for c in range(8):
                filled_above = False
                for r in range(8):
                    if board.grid[r][c]:
                        filled_above = True
                    elif filled_above:
                        expected += 1
            self.assertEqual(survival.holes(survival.board_bits(board.grid)), expected)

    def test_unplaceable_mass_matches_brute_force(self):
        rng = random.Random(3)
        for _ in range(100):
            board = random_board(rng)
            occ = survival.board_bits(board.grid)
            expected = 0.0
            for poses in PIECE_TYPES:
                for pose in poses:
                    piece = PIECE_POOL[pose]
                    fits = any(
                        board.can_place_piece(piece, x, y)
                        for y in range(8 - len(piece.shape) + 1)
                        for x in range(8 - len(piece.shape[0]) + 1)
                    )
                    if not fits:
                        expected += 1.0 / (len(PIECE_TYPES) * len(poses))
            self.assertAlmostEqual(survival.unplaceable_mass(occ), expected, places=12)

    def test_policy_returns_legal_actions(self):
        policy = build(None)
        for seed in (11, 12, 13):
            game = Game(seed=seed)
            policy.reset(seed)
            while not game.done:
                actions = game.available_actions()
                if not actions:
                    break
                move = policy.act(game, actions)
                self.assertIn(move, actions)
                game.step(move)
            self.assertNotEqual(game.placements, 0)


if __name__ == "__main__":
    unittest.main()
