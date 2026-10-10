import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import bitboard as bb
from game import Game
from search import SearchPolicy, _cheap, plan_tray


def _tray(game):
    return [(i, bb.POSES[p.index]) for i, p in enumerate(game.pieces) if p is not None]


def _single():
    return next(p for p in bb.POSES if len(p.offsets) == 1)


class TestSearch(unittest.TestCase):
    def test_planned_moves_replay_legally_in_game(self):
        placed = 0
        for seed in range(6):
            game = Game(seed)
            rng = random.Random(seed)
            for _ in range(60):
                plan = plan_tray(bb.to_mask(game.board.grid), _tray(game), rng)
                if not plan:
                    self.assertFalse(game.available_actions())
                    break
                for gi, anchor in plan:
                    move = (gi, anchor % bb.W, anchor // bb.W)
                    self.assertIn(move, game.available_actions())
                    game.step(move)
                    placed += 1
        self.assertGreater(placed, 0)

    def test_same_seed_same_moves(self):
        def play(seed):
            game = Game(seed)
            policy = SearchPolicy()
            policy.reset(seed)
            moves = []
            for _ in range(40):
                actions = game.available_actions()
                if not actions:
                    break
                move = policy.act(game, actions)
                moves.append(move)
                game.step(move)
            return moves

        self.assertEqual(play(3), play(3))

    def test_nearly_full_board_fills_a_free_cell(self):
        occ = bb.FULL & ~((1 << 0) | (1 << 9))
        self.assertIn(plan_tray(occ, [(0, _single())], random.Random(1)), ([(0, 0)], [(0, 9)]))

    def test_leaf_scores_position_not_only_piece_size(self):
        single = _single()
        corner = _cheap(*bb.clear_full(bb.place(0, single, 0)))
        centre = _cheap(*bb.clear_full(bb.place(0, single, 3 * bb.W + 3)))
        self.assertNotEqual(corner, centre)

    def test_full_board_gives_empty_plan(self):
        self.assertEqual(plan_tray(bb.FULL, [(0, _single())], random.Random(1)), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
