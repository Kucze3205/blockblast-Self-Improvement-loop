"""
Testy polityki SearchPolicy: bitboard zgodny z prostą implementacją na listach,
DFS grywalności tacki zgodny z pełnym przeszukiwaniem, kontrakt policies.build.
"""
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import policies
import search_policy
from game import Game
from pieces import PIECE_POOL, PIECE_TYPES
from search_policy import (
    HARD_MULTISETS,
    _cheap,
    _clear,
    _fit_penalty,
    _to_bits,
    _tray_ok,
)


def ref_clear(grid):
    rows = [y for y in range(8) if all(grid[y])]
    cols = [x for x in range(8) if all(grid[y][x] for y in range(8))]
    out = [row[:] for row in grid]
    for y in rows:
        out[y] = [0] * 8
    for x in cols:
        for y in range(8):
            out[y][x] = 0
    return out, len(rows) + len(cols)


def ref_cheap(grid):
    def blocked(x, y):
        return not (0 <= x < 8 and 0 <= y < 8) or grid[y][x] == 1

    trans = 0
    for y in range(8):
        seq = [1] + grid[y] + [1]
        trans += sum(seq[i] != seq[i + 1] for i in range(9))
    for x in range(8):
        seq = [1] + [grid[y][x] for y in range(8)] + [1]
        trans += sum(seq[i] != seq[i + 1] for i in range(9))
    pockets = border = occ = 0
    for y in range(8):
        for x in range(8):
            if grid[y][x]:
                occ += 1
                continue
            if sum(blocked(x + dx, y + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))) >= 3:
                pockets += 1
            if x in (0, 7) or y in (0, 7):
                border += 1
    return -1.4 * occ - 0.75 * pockets - 1.5 * trans - 2.0 * border


def ref_playable(grid, poses):
    def rec(g, rem):
        if not rem:
            return True
        for i, p in enumerate(rem):
            shape = PIECE_POOL[p].shape
            for y in range(8 - len(shape) + 1):
                for x in range(8 - len(shape[0]) + 1):
                    cells = [(y + dy, x + dx) for dy, row in enumerate(shape) for dx, c in enumerate(row) if c]
                    if any(g[cy][cx] for cy, cx in cells):
                        continue
                    ng = [r[:] for r in g]
                    for cy, cx in cells:
                        ng[cy][cx] = 1
                    ng, _ = ref_clear(ng)
                    if rec(ng, rem[:i] + rem[i + 1:]):
                        return True
        return False

    return rec(grid, list(poses))


def bits_to_grid(bits):
    return [[(bits >> (8 * y + x)) & 1 for x in range(8)] for y in range(8)]


def random_grid(rng, density):
    return [[1 if rng.random() < density else 0 for _ in range(8)] for _ in range(8)]


class SearchPolicyTest(unittest.TestCase):
    def setUp(self):
        self._budget = search_policy.DFS_BUDGET
        search_policy.DFS_BUDGET = 10 ** 9

    def tearDown(self):
        search_policy.DFS_BUDGET = self._budget

    def test_clear_matches_reference(self):
        rng = random.Random(1)
        for _ in range(300):
            grid = random_grid(rng, rng.choice((0.5, 0.8, 0.95)))
            cleared, lines = _clear(_to_bits(grid))
            ref, ref_lines = ref_clear(grid)
            self.assertEqual(bits_to_grid(cleared), ref)
            self.assertEqual(lines, ref_lines)

    def test_cheap_features_match_reference(self):
        rng = random.Random(2)
        for _ in range(300):
            grid = random_grid(rng, rng.choice((0.0, 0.2, 0.5, 0.8)))
            self.assertAlmostEqual(_cheap(_to_bits(grid)), ref_cheap(grid))

    def test_tray_playability_matches_bruteforce(self):
        rng = random.Random(3)
        seen = {True: 0, False: 0}
        for _ in range(60):
            grid = random_grid(rng, rng.choice((0.2, 0.35, 0.5)))
            poses = [rng.randrange(len(PIECE_POOL)) for _ in range(3)]
            got = _tray_ok(_to_bits(grid), poses)
            self.assertEqual(got, ref_playable(grid, poses))
            seen[got] += 1
        self.assertGreater(seen[True], 0)
        self.assertGreater(seen[False], 0)

    def test_fit_penalty_extremes(self):
        self.assertEqual(_fit_penalty(0), 0)
        full = (1 << 64) - 1
        self.assertAlmostEqual(_fit_penalty(full), 400 + 80 + 12.3 * len(PIECE_TYPES))

    def test_hard_multisets_are_a_distribution(self):
        self.assertEqual(len(HARD_MULTISETS), 35)
        self.assertAlmostEqual(sum(w for _, w in HARD_MULTISETS), 1.0)

    def test_plan_moves_are_legal_on_empty_board(self):
        game = Game(5)
        policy = policies.build(None)
        policy.reset(5)
        slots = [(i, p.index) for i, p in enumerate(game.pieces)]
        for move in policy._plan(_to_bits(game.board.grid), slots):
            self.assertNotEqual(game.step(move)[3], "wrong_placement")

    def test_build_contract_and_determinism(self):
        def run(seed):
            game = Game(seed)
            policy = policies.build(None)
            policy.reset(seed)
            moves = []
            while not game.done and len(moves) < 40:
                actions = game.available_actions()
                move = policy.act(game, actions)
                self.assertIn(move, actions)
                moves.append(move)
                game.step(move)
            return moves

        self.assertEqual(run(7), run(7))


if __name__ == "__main__":
    unittest.main()
