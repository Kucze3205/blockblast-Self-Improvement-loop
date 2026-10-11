"""Testy wykładalności tacki w policies.py: wersja bitowa względem referencji na listach."""
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import policies as P
from game import Game
from pieces import PIECE_POOL


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
            for x, y in P._positions(g, shape):
                ng, _ = P._place(g, shape, x, y)
                if dfs(ng, left & ~(1 << j)):
                    return True
        return False

    return dfs(grid, (1 << len(tray)) - 1)


class TrayPlayableTest(unittest.TestCase):
    def test_matches_list_reference_on_random_boards(self):
        rng = random.Random(7)
        for _ in range(150):
            density = rng.uniform(0.1, 0.5)
            grid = [[int(rng.random() < density) for _ in range(8)] for _ in range(8)]
            tray = P._sample_tray(rng)
            self.assertEqual(P._tray_ok(P._to_bits(grid), tray), _reference_ok(grid, tray))

    def test_empty_board_takes_three_square3(self):
        square3 = next(p.index for p in PIECE_POOL if p.name == "square3")
        self.assertTrue(P._tray_ok(0, [square3, square3, square3]))

    def test_full_board_takes_nothing(self):
        one_cell = next(p.index for p in PIECE_POOL if p.name == "1x1")
        self.assertFalse(P._tray_ok(P.FULL, [one_cell]))

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
