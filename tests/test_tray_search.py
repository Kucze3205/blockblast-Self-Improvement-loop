"""
Testy kontraktu `policies.build` i dokończalności tacki na bitboardzie.

Dokończalność jest sprawdzana względem silnika (board.py), a nie względem samej siebie.
Testy nie mierzą jakości gry.
"""
import os
import random
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from board import Board
from game import Game
from pieces import PIECE_POOL, Piece
from policies import build
from risk import POSE_KEYS, death_probability, sample_trays
from tray_search import clear_count, completable, fits, from_grid, leaf, shape_key, tray_finals


def brute_completable(grid, shapes):
    if not shapes:
        return True
    for i, shape in enumerate(shapes):
        piece = Piece(shape, "ref", -1)
        for y in range(8 - len(shape) + 1):
            for x in range(8 - len(shape[0]) + 1):
                trial = Board()
                trial.grid = [row[:] for row in grid]
                if not trial.place_piece(piece, x, y):
                    continue
                trial.clear_lines(*trial.check_full_lines())
                if brute_completable(trial.grid, shapes[:i] + shapes[i + 1:]):
                    return True
    return False


def random_grid(rng, density):
    return [[int(rng.random() < density) for _ in range(8)] for _ in range(8)]


class CompletableTest(unittest.TestCase):
    def test_matches_engine_on_random_trays(self):
        rng = random.Random(7)
        for _ in range(300):
            grid = random_grid(rng, rng.uniform(0.0, 0.6))
            shapes = [rng.choice(PIECE_POOL).shape for _ in range(rng.randint(1, 3))]
            expected = brute_completable(grid, shapes)
            got = completable(from_grid(grid), [shape_key(s) for s in shapes])
            self.assertEqual(got, expected, (grid, shapes))

    def test_empty_tray_is_completable(self):
        self.assertTrue(completable(0, []))


class BuildPolicyTest(unittest.TestCase):
    def test_plays_legal_moves_in_engine_games(self):
        for seed in range(3):
            game = Game(seed=seed)
            policy = build(None)
            policy.reset(seed)
            for _ in range(150):
                if game.done:
                    break
                actions = game.available_actions()
                if not actions:
                    break
                move = policy.act(game, actions)
                self.assertIn(move, actions)
                _, _, _, reason = game.step(move)
                self.assertNotEqual(reason, "wrong_placement")

    def test_accepts_bridge_namespace(self):
        board = Board()
        pieces = [Piece(PIECE_POOL[0].shape, "slot0", -1), None,
                  Piece(PIECE_POOL[5].shape, "slot2", -1)]
        game = SimpleNamespace(board=board, pieces=pieces, combo=0)
        actions = [(i, x, y) for i, p in enumerate(pieces) if p is not None
                   for y in range(8) for x in range(8) if board.can_place_piece(p, x, y)]
        self.assertIn(build(None).act(game, actions), actions)


def brute_finals(grid, shapes, out):
    if not shapes:
        out.add(from_grid(grid))
        return
    for i, shape in enumerate(shapes):
        piece = Piece(shape, "ref", -1)
        for y in range(8 - len(shape) + 1):
            for x in range(8 - len(shape[0]) + 1):
                trial = Board()
                trial.grid = [row[:] for row in grid]
                if not trial.place_piece(piece, x, y):
                    continue
                trial.clear_lines(*trial.check_full_lines())
                brute_finals(trial.grid, shapes[:i] + shapes[i + 1:], out)


class TrayFinalsTest(unittest.TestCase):
    def test_full_search_matches_engine_outcomes(self):
        rng = random.Random(11)
        for _ in range(40):
            grid = random_grid(rng, rng.uniform(0.3, 0.6))
            shapes = [rng.choice(PIECE_POOL).shape for _ in range(rng.randint(1, 3))]
            expected = set()
            brute_finals(grid, shapes, expected)
            pieces = [(i, shape_key(s)) for i, s in enumerate(shapes)]
            finals = tray_finals(from_grid(grid), pieces)
            self.assertEqual({board for _, board, _ in finals}, expected, (grid, shapes))
            for _, _, (idx, x, y) in finals:
                probe = Board()
                probe.grid = [row[:] for row in grid]
                self.assertTrue(probe.can_place_piece(Piece(shapes[idx], "ref", -1), x, y))

    def test_beam_does_not_prefer_top_left(self):
        tray = [(0, shape_key([[1]])), (1, shape_key([[1, 1]])), (2, shape_key([[1, 1, 1]]))]
        rows = {move[2] for _, _, move in tray_finals(0, tray, 40)}
        self.assertGreater(len(rows), 1)


def brute_leaf_terms(grid):
    empty = {(r, c) for r in range(8) for c in range(8) if not grid[r][c]}
    isolated = sum(1 for r, c in empty
                   if not any((r + dr, c + dc) in empty for dr, dc in ((0, 1), (0, -1), (1, 0), (-1, 0))))
    transitions = sum(grid[r][c] != grid[r][c + 1] for r in range(8) for c in range(7))
    transitions += sum(grid[r][c] != grid[r + 1][c] for r in range(7) for c in range(8))
    border = sum(1 for r, c in empty if r in (0, 7) or c in (0, 7))
    return 64 - len(empty), isolated, transitions, border


class LeafTest(unittest.TestCase):
    def test_leaf_matches_brute_force_terms(self):
        rng = random.Random(9)
        for _ in range(200):
            grid = random_grid(rng, rng.uniform(0.0, 0.8))
            occupied, isolated, transitions, border = brute_leaf_terms(grid)
            expected = -1.4 * occupied - 0.75 * isolated - 1.5 * transitions - 2.0 * border
            self.assertAlmostEqual(leaf(from_grid(grid), 0), expected, places=9, msg=grid)

    def test_clear_count_matches_engine(self):
        rng = random.Random(4)
        for _ in range(300):
            grid = random_grid(rng, rng.uniform(0.5, 0.95))
            ref = Board()
            ref.grid = [row[:] for row in grid]
            rows, cols = ref.check_full_lines()
            board, count = clear_count(from_grid(grid))
            self.assertEqual(count, len(rows) + len(cols), grid)
            ref.clear_lines(rows, cols)
            self.assertEqual(board, from_grid(ref.grid), grid)


class RiskTest(unittest.TestCase):
    def test_fits_matches_engine_for_all_poses(self):
        rng = random.Random(5)
        for _ in range(60):
            grid = random_grid(rng, rng.uniform(0.0, 0.7))
            ref = Board()
            ref.grid = [row[:] for row in grid]
            for p, key in enumerate(POSE_KEYS):
                engine = any(ref.can_place_piece(Piece(PIECE_POOL[p].shape, "ref", -1), x, y)
                             for y in range(8) for x in range(8))
                self.assertEqual(fits(from_grid(grid), key), engine, (p, grid))

    def test_death_probability_bounds(self):
        trays = sample_trays(64)
        full = from_grid([[1] * 8 for _ in range(8)])
        self.assertEqual(death_probability(full, trays), 1.0)
        rng = random.Random(3)
        for _ in range(20):
            value = death_probability(from_grid(random_grid(rng, 0.4)), trays)
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 1.0)


if __name__ == "__main__":
    unittest.main()
