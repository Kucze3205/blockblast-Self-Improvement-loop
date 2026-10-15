"""Testy tacki w beam.py: wersja bitowa względem referencji na listach, ogon mieszanych tacek."""
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from types import SimpleNamespace

import beam as B
import policies
from board import Board
from game import Game
from pieces import PIECE_POOL, Piece

N = 8


def _fits(grid, shape, x, y):
    for dy, row in enumerate(shape):
        for dx, cell in enumerate(row):
            if cell and grid[y + dy][x + dx]:
                return False
    return True


def _positions(grid, shape):
    ph, pw = len(shape), len(shape[0])
    return [
        (x, y)
        for y in range(N - ph + 1)
        for x in range(N - pw + 1)
        if _fits(grid, shape, x, y)
    ]


def _place(grid, shape, x, y):
    g = [row[:] for row in grid]
    for dy, row in enumerate(shape):
        for dx, cell in enumerate(row):
            if cell:
                g[y + dy][x + dx] = 1
    rows = [r for r in range(N) if all(g[r])]
    cols = [c for c in range(N) if all(g[r][c] for r in range(N))]
    for r in rows:
        g[r] = [0] * N
    for c in cols:
        for r in range(N):
            g[r][c] = 0
    return g, len(rows) + len(cols)


def _settle(grid):
    return _place(grid, [[0]], 0, 0)[0]


def _reference_ok(grid, tray):
    seen = set()

    def dfs(g, left):
        if not left:
            return True
        key = (tuple(map(tuple, g)), left)
        if key in seen:
            return False
        seen.add(key)
        for j, idx in enumerate(tray):
            if not (left >> j) & 1:
                continue
            shape = PIECE_POOL[idx].shape
            for x, y in _positions(g, shape):
                ng, _ = _place(g, shape, x, y)
                if dfs(ng, left & ~(1 << j)):
                    return True
        return False

    return dfs(grid, (1 << len(tray)) - 1)


class TrayPlayableTest(unittest.TestCase):
    def test_matches_list_reference_on_random_boards(self):
        rng = random.Random(7)
        for _ in range(150):
            density = rng.uniform(0.1, 0.5)
            grid = _settle([[int(rng.random() < density) for _ in range(8)] for _ in range(8)])
            tray = B._sample_tray(rng)
            self.assertEqual(B._tray_ok(B._to_bits(grid), tray), _reference_ok(grid, tray))

    def test_empty_board_takes_three_square3(self):
        square3 = next(p.index for p in PIECE_POOL if p.name == "square3")
        self.assertTrue(B._tray_ok(0, [square3, square3, square3]))

    def test_full_board_takes_nothing(self):
        one_cell = next(p.index for p in PIECE_POOL if p.name == "1x1")
        self.assertFalse(B._tray_ok(B.FULL, [one_cell]))

    def test_mixed_trays_have_a_non_hard_piece(self):
        for tray in B._mixed_trays(random.Random(3)):
            self.assertTrue(any(PIECE_POOL[i].type_index not in B.HARD_TYPES for i in tray))

    def test_tail_penalty_is_zero_on_empty_board(self):
        self.assertEqual(B.tail_penalty(0, B._mixed_trays(random.Random(4))), 0.0)

    def test_next_value_equals_unpruned_max(self):
        rng = random.Random(11)
        policy = B.BeamPolicy()
        for _ in range(12):
            density = rng.uniform(0.2, 0.5)
            b = B._to_bits(_settle([[int(rng.random() < density) for _ in range(8)] for _ in range(8)]))
            poses = B._sample_tray(rng)
            triples = B._hard_triples(rng)
            states = B.plan(b, [(k, B.PLACEMENTS[i]) for k, i in enumerate(poses)], B.LOOK_BEAM, B.LOOK_BEAM)
            expected = None
            if states:
                expected = max(B.cheap(s[0], s[2]) - B.risk(s[0], triples) for s in states[:2])
            self.assertEqual(policy._next_value(b, triples, poses), expected)

    def test_policy_plays_legal_moves(self):
        game = Game(1)
        policy = policies.build(None)
        policy.reset(1)
        for _ in range(40):
            actions = game.available_actions()
            if not actions:
                break
            move = policy.act(game, actions)
            self.assertIn(move, actions)
            game.step(move)
            if game.done:
                break

    def test_bridge_pieces_without_index_give_same_move(self):
        rng = random.Random(5)
        for _ in range(20):
            density = rng.uniform(0.1, 0.4)
            board = Board()
            board.grid = _settle([[int(rng.random() < density) for _ in range(8)] for _ in range(8)])
            pool = [PIECE_POOL[i] for i in B._sample_tray(rng)]
            bridge = [Piece(p.shape, f"slot{k}", -1) for k, p in enumerate(pool)]
            actions = [
                (k, x, y)
                for k, p in enumerate(pool)
                for y in range(N)
                for x in range(N)
                if board.can_place_piece(p, x, y)
            ]
            if not actions:
                continue
            pool_policy, bridge_policy = B.BeamPolicy(), B.BeamPolicy()
            pool_policy.reset(9)
            bridge_policy.reset(9)
            self.assertEqual(
                bridge_policy.act(SimpleNamespace(board=board, pieces=bridge, combo=0), actions),
                pool_policy.act(SimpleNamespace(board=board, pieces=pool, combo=0), actions),
            )


if __name__ == "__main__":
    unittest.main()
