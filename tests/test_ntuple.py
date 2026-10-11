"""Testy reprezentacji planszy i polityki n-krotek (valuation.py, policies.py)."""
import json
import os
import random
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import valuation
from board import Board
from game import Game
from pieces import PIECE_POOL
from policies import EVAL_BEAM, NTUPLE_FILE, GreedyPolicy, NTuplePolicy, build

FULL = (1 << 64) - 1


def random_grid(rng, density):
    return [[1 if rng.random() < density else 0 for _ in range(8)] for _ in range(8)]


def naive_positions(grid):
    out = []
    for r in range(8):
        bits = sum(1 << c for c in range(8) if grid[r][c])
        out.append(r * valuation.LINE_ENTRIES + bits)
    for c in range(8):
        bits = sum(1 << r for r in range(8) if grid[r][c])
        out.append((8 + c) * valuation.LINE_ENTRIES + bits)
    for i, (x0, y0) in enumerate(valuation.WINDOW_ORIGINS):
        idx = sum(
            1 << (3 * dy + dx)
            for dy in range(3)
            for dx in range(3)
            if grid[y0 + dy][x0 + dx]
        )
        out.append(valuation.WINDOW_BASE + i * valuation.WINDOW_ENTRIES + idx)
    return out


class TestBoardMasks(unittest.TestCase):
    def test_clear_full_matches_board(self):
        rng = random.Random(1)
        for _ in range(200):
            board = Board()
            board.grid = random_grid(rng, 0.8)
            occ = valuation.occupancy(board.grid)
            rows, cols = board.check_full_lines()
            board.clear_lines(rows, cols)
            self.assertEqual(valuation.clear_full(occ), valuation.occupancy(board.grid))

    def test_piece_mask_matches_board_placement(self):
        rng = random.Random(3)
        for _ in range(10):
            board = Board()
            board.grid = random_grid(rng, 0.3)
            occ = valuation.occupancy(board.grid)
            for piece in PIECE_POOL:
                for y in range(8 - len(piece.shape) + 1):
                    for x in range(8 - len(piece.shape[0]) + 1):
                        if not board.can_place_piece(piece, x, y):
                            continue
                        placed = board.copy()
                        placed.place_piece(piece, x, y)
                        self.assertEqual(
                            valuation.occupancy(placed.grid),
                            occ | valuation.piece_mask(piece.shape, x, y),
                        )

    def test_fit_rule_matches_board(self):
        rng = random.Random(2)
        for _ in range(10):
            board = Board()
            board.grid = random_grid(rng, 0.4)
            occ = valuation.occupancy(board.grid)
            for piece in PIECE_POOL:
                mask, shifts = valuation.placements(valuation.shape_key(piece.shape))
                fits = {s for s in shifts if not occ & (mask << s)}
                h, w = len(piece.shape), len(piece.shape[0])
                expected = {
                    8 * y + x
                    for y in range(8 - h + 1)
                    for x in range(8 - w + 1)
                    if board.can_place_piece(piece, x, y)
                }
                self.assertEqual(fits, expected)


class TestPositions(unittest.TestCase):
    def test_positions_match_naive_and_stay_in_table(self):
        rng = random.Random(4)
        for _ in range(300):
            grid = random_grid(rng, rng.random())
            pos = valuation.positions(valuation.occupancy(grid))
            self.assertEqual(pos, naive_positions(grid))
            self.assertEqual(len(pos), valuation.TUPLE_COUNT)
            self.assertTrue(all(0 <= p < valuation.TABLE_SIZE for p in pos))


class TestCompletable(unittest.TestCase):
    ONE = valuation.shape_key([[1]])
    BEAM2 = valuation.shape_key([[1, 1]])

    def test_single_free_cell(self):
        occ = FULL & ~1
        self.assertTrue(valuation.completable(occ, (self.ONE,)))
        self.assertFalse(valuation.completable(occ, (self.BEAM2,)))
        self.assertTrue(valuation.completable(occ, (self.ONE, self.ONE)))
        self.assertTrue(valuation.completable(occ, ()))

    def test_clearing_frees_room_for_next_piece(self):
        occ = FULL & ~(1 | (1 << 8))
        self.assertTrue(valuation.completable(occ, (self.ONE, self.BEAM2)))


class TestBuildAndPolicy(unittest.TestCase):
    def test_missing_weights_fall_back(self):
        self.assertIsInstance(build(None), GreedyPolicy)
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsInstance(build(tmp), GreedyPolicy)

    def test_loads_trained_table(self):
        table = [0.0] * valuation.TABLE_SIZE
        table[5] = 0.25
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, NTUPLE_FILE), "w", encoding="utf-8") as fh:
                json.dump(valuation.dump_table(table), fh)
            policy = build(tmp)
        self.assertIsInstance(policy, NTuplePolicy)
        self.assertEqual(policy.beam, EVAL_BEAM)
        self.assertAlmostEqual(policy.table[5], 0.25)

    def test_act_and_explore_return_legal_actions(self):
        rng = random.Random(5)
        table = [rng.uniform(-0.01, 0.01) for _ in range(valuation.TABLE_SIZE)]
        for beam in (1, EVAL_BEAM):
            policy = NTuplePolicy(table, beam=beam)
            for seed in range(3):
                game = Game(seed=seed)
                policy.reset(seed)
                for _ in range(60):
                    actions = game.available_actions()
                    if not actions:
                        break
                    chosen = policy.act(game, actions)
                    self.assertIn(chosen, actions)
                    self.assertIn(policy.explore(game, actions, rng), actions)
                    _, _, done, reason = game.step(chosen)
                    self.assertNotEqual(reason, "wrong_placement")
                    if done:
                        break


if __name__ == "__main__":
    unittest.main()
