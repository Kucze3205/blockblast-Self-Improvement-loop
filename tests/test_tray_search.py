import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import policies
from game import Game
from pieces import PIECE_POOL
from policies import (
    _HARD_MULTISETS,
    _bitboard,
    _clear_lines,
    _hard_risk,
    _perimeter,
    _tray_playable,
)


def ref_playable(grid, poses):
    def rec(g, rem):
        if not rem:
            return True
        for i, pose in enumerate(rem):
            shape = PIECE_POOL[pose].shape
            for y in range(8 - len(shape) + 1):
                for x in range(8 - len(shape[0]) + 1):
                    cells = [(y + dy, x + dx) for dy, row in enumerate(shape) for dx, c in enumerate(row) if c]
                    if any(g[cy][cx] for cy, cx in cells):
                        continue
                    ng = [r[:] for r in g]
                    for cy, cx in cells:
                        ng[cy][cx] = 1
                    full_rows = [yy for yy in range(8) if all(ng[yy])]
                    full_cols = [xx for xx in range(8) if all(ng[yy][xx] for yy in range(8))]
                    for yy in full_rows:
                        ng[yy] = [0] * 8
                    for xx in full_cols:
                        for yy in range(8):
                            ng[yy][xx] = 0
                    if rec(ng, rem[:i] + rem[i + 1:]):
                        return True
        return False

    return rec(grid, list(poses))


def random_grid(rng, density):
    return [[1 if rng.random() < density else 0 for _ in range(8)] for _ in range(8)]


def bits_to_grid(bits):
    return [[(bits >> (8 * y + x)) & 1 for x in range(8)] for y in range(8)]


class TraySearchTest(unittest.TestCase):
    def setUp(self):
        self._budget = policies.TRAY_DFS_BUDGET
        policies.TRAY_DFS_BUDGET = 10 ** 9

    def tearDown(self):
        policies.TRAY_DFS_BUDGET = self._budget

    def test_cleared_cells_do_not_add_perimeter(self):
        pre = 0
        for x in range(8):
            pre |= 1 << (8 * 3 + x)
        for y in (2, 4):
            for x in range(1, 8):
                pre |= 1 << (8 * y + x)
        after, lines = _clear_lines(pre)
        self.assertEqual(lines, 1)
        self.assertEqual(_perimeter(after | (pre & ~after)), _perimeter(pre))

    def test_tray_playable_matches_bruteforce(self):
        rng = random.Random(3)
        seen = {True: 0, False: 0}
        for _ in range(40):
            grid = random_grid(rng, rng.choice((0.2, 0.35, 0.5)))
            poses = [rng.randrange(len(PIECE_POOL)) for _ in range(3)]
            got = _tray_playable(_bitboard(grid), poses)
            self.assertEqual(got, ref_playable(grid, poses))
            seen[got] += 1
        self.assertGreater(seen[True], 0)
        self.assertGreater(seen[False], 0)

    def test_hard_multisets_are_a_distribution(self):
        self.assertEqual(len(_HARD_MULTISETS), 286)
        self.assertAlmostEqual(sum(w for _, w in _HARD_MULTISETS), 1.0)

    def test_hard_risk_extremes(self):
        self.assertEqual(_hard_risk(0), 0)
        self.assertAlmostEqual(_hard_risk((1 << 64) - 1), 1.0)

    def test_plan_moves_are_legal_and_complete(self):
        for seed in (1, 2):
            game = Game(seed)
            policy = policies.build(None)
            policy.reset(seed)
            placed = 0
            while not game.done and placed < 60:
                actions = game.available_actions()
                move = policy.act(game, actions)
                self.assertIn(move, actions)
                result = game.step(move)
                self.assertNotEqual(result[3], "wrong_placement")
                placed += 1

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
