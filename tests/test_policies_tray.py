"""Testy wykładalności tacki w policies.py: wersja bitowa względem referencji na listach."""
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import policies as P
from game import Game
from generator import Generator
from pieces import PIECE_POOL

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
    """Usuwa pełne linie, których gra nie zostawia między ruchami."""
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
            tray = P._sample_tray(rng)
            self.assertEqual(P._tray_ok(P._to_bits(grid), tray), _reference_ok(grid, tray))

    def test_empty_board_takes_three_square3(self):
        square3 = next(p.index for p in PIECE_POOL if p.name == "square3")
        self.assertTrue(P._tray_ok(0, [square3, square3, square3]))

    def test_full_board_takes_nothing(self):
        one_cell = next(p.index for p in PIECE_POOL if p.name == "1x1")
        self.assertFalse(P._tray_ok(P.FULL, [one_cell]))

    def test_mixed_trays_have_a_non_hard_piece(self):
        for tray in P._mixed_trays(random.Random(3)):
            self.assertTrue(any(PIECE_POOL[i].type_index not in P.HARD_TYPES for i in tray))

    def test_tail_penalty_is_zero_on_empty_board(self):
        self.assertEqual(P.tail_penalty(0, P._mixed_trays(random.Random(4))), 0.0)

    def test_next_value_equals_unpruned_max(self):
        rng = random.Random(9)
        triples = P._hard_triples(rng)
        mixed = P._mixed_trays(rng)
        hits = 0
        for _ in range(40):
            density = rng.uniform(0.1, 0.5)
            b = P._to_bits(_settle([[int(rng.random() < density) for _ in range(8)] for _ in range(8)]))
            poses = P._sample_tray(rng)
            states = P._next_states(b, poses)
            if not states:
                continue
            hits += 1
            expected = max(P.cheap(s[0], s[2]) - P.risk(s[0], triples) - P.tail_penalty(s[0], mixed) for s in states)
            self.assertEqual(P._next_value(states, triples, mixed), expected)
        self.assertGreater(hits, 0)

    def test_hard_share_matches_generator(self):
        gen = Generator(11)
        n = 30000
        hits = sum(all(p.type_index in P.HARD_TYPES for p in gen.next_pieces()) for _ in range(n))
        self.assertAlmostEqual(hits / n, P.HARD_SHARE, delta=0.004)

    def test_policy_plays_legal_moves(self):
        game = Game(1)
        policy = P.build(None)
        policy.reset(1)
        for _ in range(40):
            actions = game.available_actions()
            if not actions:
                break
            move = policy.act(game, actions)
            self.assertIn(move, actions)
            _, _, done, _ = game.step(move)
            if done:
                break


if __name__ == "__main__":
    unittest.main()
