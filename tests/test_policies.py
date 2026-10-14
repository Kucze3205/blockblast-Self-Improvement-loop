"""
Testy planera tacki: bitboardy zgodne z Board, układalność tacki zgodna z brute force.
"""
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import planner
from board import Board
from game import Game
from pieces import PIECE_POOL
from policies import build

W, H = Board.WIDTH, Board.HEIGHT


def random_grid(rng):
    while True:
        grid = [[1 if rng.random() < 0.4 else 0 for _ in range(W)] for _ in range(H)]
        if any(0 in row for row in grid):
            return grid


def brute_tray(grid, pieces):
    if not pieces:
        return True
    for k, piece in enumerate(pieces):
        for y in range(H - len(piece.shape) + 1):
            for x in range(W - len(piece.shape[0]) + 1):
                board = Board()
                board.grid = [row[:] for row in grid]
                if board.place_piece(piece, x, y):
                    rows, cols = board.check_full_lines()
                    board.clear_lines(rows, cols)
                    if brute_tray(board.grid, pieces[:k] + pieces[k + 1:]):
                        return True
    return False


class BitboardTests(unittest.TestCase):
    def test_transpose_matches_definition(self):
        rng = random.Random(1)
        for _ in range(300):
            b = rng.getrandbits(64)
            expected = 0
            for r in range(H):
                for c in range(W):
                    if (b >> (W * r + c)) & 1:
                        expected |= 1 << (W * c + r)
            self.assertEqual(planner.transpose(b), expected)

    def test_clear_matches_board(self):
        rng = random.Random(2)
        for _ in range(300):
            grid = [[1 if rng.random() < 0.8 else 0 for _ in range(W)] for _ in range(H)]
            board = Board()
            board.grid = [row[:] for row in grid]
            rows, cols = board.check_full_lines()
            board.clear_lines(rows, cols)
            cleared, lines = planner.clear(planner.to_bits(grid))
            self.assertEqual(cleared, planner.to_bits(board.grid))
            self.assertEqual(lines, len(rows) + len(cols))

    def test_placements_match_board(self):
        rng = random.Random(3)
        for _ in range(50):
            grid = random_grid(rng)
            board = Board()
            board.grid = [row[:] for row in grid]
            bits = planner.to_bits(grid)
            for pose, piece in enumerate(PIECE_POOL):
                legal = {(x, y) for x, y, m in planner.PLACEMENTS[pose] if not (bits & m)}
                expected = {
                    (x, y)
                    for y in range(H - len(piece.shape) + 1)
                    for x in range(W - len(piece.shape[0]) + 1)
                    if board.can_place_piece(piece, x, y)
                }
                self.assertEqual(legal, expected)

    def test_transitions_of_single_cell(self):
        self.assertEqual(planner.trans(1 << (W * 3 + 3)), 4)
        self.assertEqual(planner.trans(0), 0)

    def test_tray_placeability_matches_brute_force(self):
        rng = random.Random(4)
        for _ in range(150):
            grid = random_grid(rng)
            poses = tuple(rng.randrange(len(PIECE_POOL)) for _ in range(3))
            fast = planner.places_all(planner.to_bits(grid), poses, [10**9])
            slow = brute_tray(grid, [PIECE_POOL[p] for p in poses])
            self.assertEqual(fast, slow)

    def test_single_risk_bounds(self):
        self.assertEqual(planner.single_risk(0), 0.0)
        self.assertAlmostEqual(sum(planner.POSE_WEIGHT), 1.0)
        only_hole = planner.to_bits([[1] * W for _ in range(H)]) & ~1
        self.assertGreater(planner.single_risk(only_hole), 0.9)


class PolicyTests(unittest.TestCase):
    def test_build_plays_legal_moves(self):
        policy = build(None)
        for seed in range(3):
            game = Game(seed=seed)
            policy.reset(seed)
            for _ in range(60):
                actions = game.available_actions()
                if game.done or not actions:
                    break
                move = policy.act(game, actions)
                self.assertIn(move, actions)
                game.step(move)


if __name__ == "__main__":
    unittest.main()
