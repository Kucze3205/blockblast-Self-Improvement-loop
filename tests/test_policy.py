import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game import Game
from pieces import PIECE_TYPES
from search_policy import (
    FULL,
    HARD_PENALTY,
    SearchPolicy,
    _fits_all,
    _hard_penalty,
    _sample_hard_tray,
    place,
    pockets,
    to_bits,
    transitions,
)


def grid_from(rows):
    return [list(row) for row in rows]


def sampled_trays(seed, count=16):
    rng = random.Random(seed)
    return [_sample_hard_tray(rng) for _ in range(count)]


class BitboardHelpersTest(unittest.TestCase):
    def test_place_clears_full_row(self):
        board = to_bits(grid_from([[1] * 7 + [0]] + [[0] * 8 for _ in range(7)]))
        new_board, lines = place(board, 1 << 7)
        self.assertEqual(lines, 1)
        self.assertEqual(new_board, 0)

    def test_transitions_on_empty_board_count_walls(self):
        self.assertEqual(transitions(0), 32)

    def test_transitions_around_single_cell(self):
        self.assertEqual(transitions(1 << (8 * 3 + 3)), 36)

    def test_transitions_on_full_board(self):
        self.assertEqual(transitions(FULL), 0)

    def test_pockets_need_three_blocked_neighbours(self):
        rows = [[0] * 8 for _ in range(8)]
        rows[2][3] = 1
        rows[4][3] = 1
        rows[3][2] = 1
        self.assertEqual(pockets(to_bits(rows)), 1)


class TrayPlayabilityTest(unittest.TestCase):
    def test_empty_board_takes_every_sampled_hard_tray(self):
        self.assertEqual(_hard_penalty(0, sampled_trays(1)), 0.0)

    def test_full_board_takes_no_tray(self):
        self.assertEqual(_hard_penalty(FULL, sampled_trays(1)), HARD_PENALTY)

    def test_isolated_free_cells_take_no_beam2(self):
        rows = [[1 if (x + y) % 2 == 0 else 0 for x in range(8)] for y in range(8)]
        board = to_bits(grid_from(rows))
        self.assertFalse(_fits_all(board, [PIECE_TYPES[1][0], PIECE_TYPES[0][0], PIECE_TYPES[0][0]], [150]))
        self.assertTrue(_fits_all(board, [PIECE_TYPES[0][0]] * 3, [150]))


class SearchPolicyTest(unittest.TestCase):
    def test_plays_only_legal_moves(self):
        for seed in (1, 2, 3):
            game = Game(seed=seed)
            policy = SearchPolicy()
            policy.reset(seed)
            moves = 0
            while not game.done and moves < 60:
                actions = game.available_actions()
                if not actions:
                    break
                action = policy.act(game, actions)
                self.assertIn(action, actions)
                game.step(action)
                moves += 1
            self.assertGreater(moves, 0)


if __name__ == "__main__":
    unittest.main()
