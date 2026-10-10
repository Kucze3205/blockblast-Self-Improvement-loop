"""
Testy wiązki po tacce na bitboardach: każdy prymityw porównany z silnikiem (Board/Game).
"""
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from board import Board
from game import Game
from pieces import PIECE_POOL, PIECE_TYPES
from policies import build
from tray_search import (
    HARD_MULTISETS,
    HARD_TYPES,
    SLOT_P,
    W_BORDER,
    W_ISO,
    W_LINE,
    W_OCC,
    W_TRANS,
    _dead_tray_prob,
    _fit,
    _joint_playable,
    _leaf,
    _pockets,
    _settle,
    _transitions,
    occupancy,
)


def random_grid(rng, density):
    return [[1 if rng.random() < density else 0 for _ in range(8)] for _ in range(8)]


def board_from(grid):
    board = Board()
    board.grid = [row[:] for row in grid]
    return board


def brute_playable(grid, pieces):
    if not pieces:
        return True
    for i, piece in enumerate(pieces):
        rest = pieces[:i] + pieces[i + 1:]
        for y in range(8 - len(piece.shape) + 1):
            for x in range(8 - len(piece.shape[0]) + 1):
                board = board_from(grid)
                if board.can_place_piece(piece, x, y):
                    board.place_piece(piece, x, y)
                    rows, cols = board.check_full_lines()
                    board.clear_lines(rows, cols)
                    if brute_playable(board.grid, rest):
                        return True
    return False


class TestBitboardPrimitives(unittest.TestCase):
    def test_fit_matches_engine_anchors(self):
        rng = random.Random(1)
        for _ in range(40):
            grid = random_grid(rng, rng.random() * 0.6)
            occ = occupancy(grid)
            board = board_from(grid)
            for pose, piece in enumerate(PIECE_POOL):
                expect = 0
                for y in range(8 - len(piece.shape) + 1):
                    for x in range(8 - len(piece.shape[0]) + 1):
                        if board.can_place_piece(piece, x, y):
                            expect |= 1 << (y * 8 + x)
                self.assertEqual(_fit(occ, pose), expect)

    def test_settle_matches_engine_clears(self):
        rng = random.Random(2)
        for _ in range(60):
            grid = random_grid(rng, 0.5 + rng.random() * 0.45)
            board = board_from(grid)
            rows, cols = board.check_full_lines()
            board.clear_lines(rows, cols)
            settled, lines = _settle(occupancy(grid))
            self.assertEqual(settled, occupancy(board.grid))
            self.assertEqual(lines, len(rows) + len(cols))

    def test_pockets_matches_bruteforce(self):
        rng = random.Random(3)
        for _ in range(40):
            grid = random_grid(rng, rng.random() * 0.7)
            pockets = 0
            for r in range(8):
                for c in range(8):
                    if grid[r][c]:
                        continue
                    neighbours = [(r + dr, c + dc) for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1))]
                    if all(not (0 <= a < 8 and 0 <= b < 8) or grid[a][b] for a, b in neighbours):
                        pockets += 1
            self.assertEqual(_pockets(occupancy(grid)), pockets)

    def test_leaf_matches_bruteforce(self):
        rng = random.Random(6)
        for _ in range(40):
            grid = random_grid(rng, rng.random() * 0.7)
            sequences = [[1] + row + [1] for row in grid]
            sequences += [[1] + [grid[r][c] for r in range(8)] + [1] for c in range(8)]
            trans = sum(seq[i] != seq[i + 1] for seq in sequences for i in range(9))
            border = sum(
                1
                for r in range(8)
                for c in range(8)
                if not grid[r][c] and (r in (0, 7) or c in (0, 7))
            )
            occ = occupancy(grid)
            occupied = sum(map(sum, grid))
            self.assertEqual(_transitions(occ), trans)
            expect = (
                W_LINE * 2
                - W_OCC * occupied
                - W_ISO * _pockets(occ)
                - W_TRANS * trans
                - W_BORDER * border
            )
            self.assertAlmostEqual(_leaf(occ, 2), expect)

    def test_hard_multisets_cover_hard_mass(self):
        total = sum(weight for weight, _ in HARD_MULTISETS)
        hard_mass = sum(SLOT_P[p] for t in HARD_TYPES for p in PIECE_TYPES[t])
        self.assertAlmostEqual(total, hard_mass ** 3, places=12)
        self.assertAlmostEqual(total, (len(HARD_TYPES) / 15) ** 3, places=12)


class TestRiskAgainstEngine(unittest.TestCase):
    def test_dead_tray_probability_matches_enumeration(self):
        rng = random.Random(4)
        for _ in range(6):
            occ = occupancy(random_grid(rng, rng.random() * 0.6))
            dead = {p for p in range(len(PIECE_POOL)) if not _fit(occ, p)}
            expect = 0.0
            for a in range(len(PIECE_POOL)):
                for b in range(len(PIECE_POOL)):
                    for c in range(len(PIECE_POOL)):
                        if a in dead or b in dead or c in dead:
                            expect += SLOT_P[a] * SLOT_P[b] * SLOT_P[c]
            self.assertAlmostEqual(_dead_tray_prob(occ), expect, places=12)

    def test_joint_playable_matches_engine(self):
        rng = random.Random(5)
        for _ in range(30):
            grid = random_grid(rng, 0.2 + rng.random() * 0.4)
            occ = occupancy(grid)
            poses = [rng.randrange(len(PIECE_POOL)) for _ in range(3)]
            want = brute_playable(grid, [PIECE_POOL[p] for p in poses])
            self.assertEqual(_joint_playable(occ, tuple(poses), [10 ** 6]), want)


class TestPolicy(unittest.TestCase):
    def test_build_ignores_weights(self):
        for weights in (None, "weights"):
            policy = build(weights)
            policy.reset(0)

    def test_act_returns_legal_move(self):
        for seed in range(3):
            game = Game(seed=seed)
            policy = build(None)
            policy.reset(seed)
            for _ in range(40):
                actions = game.available_actions()
                if not actions:
                    break
                move = policy.act(game, actions)
                self.assertIn(tuple(move), [tuple(a) for a in actions])
                _, _, done, _ = game.step(tuple(move))
                if done:
                    break


if __name__ == "__main__":
    unittest.main()
