"""Testy polityki wiązki po tacce (policies.build)."""
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import policies
from board import Board
from game import Game
from generator import Generator
from pieces import PIECE_POOL, PIECE_TYPES


def engine_completable(board, pieces):
    if not pieces:
        return True
    for k, piece in enumerate(pieces):
        for y in range(Board.HEIGHT):
            for x in range(Board.WIDTH):
                if board.can_place_piece(piece, x, y):
                    trial = board.copy()
                    trial.place_piece(piece, x, y)
                    rows, cols = trial.check_full_lines()
                    trial.clear_lines(rows, cols)
                    if engine_completable(trial, pieces[:k] + pieces[k + 1:]):
                        return True
    return False


def board_with_middle_row_one_short():
    board = 0
    for y in range(5):
        for x in range(8):
            if (x + y) % 2 == 0:
                board |= 1 << (y * 8 + x)
    for x in range(7):
        board |= 1 << (5 * 8 + x)
    return board


class LeafValueTest(unittest.TestCase):
    def test_clearing_middle_row_is_preferred(self):
        board = board_with_middle_row_one_short()
        last_cell = 1 << (5 * 8 + 7)
        cleared, lines = policies._place_and_clear(board, last_cell)
        kept = board | last_cell
        self.assertEqual(lines, 1)
        self.assertGreater(policies._value(cleared, lines), policies._value(kept, 0))


class FitProfileTest(unittest.TestCase):
    def test_single_free_cell_fits_only_one_by_one(self):
        board = ((1 << 64) - 1) & ~1
        miss, dead_types = policies._fit_profile(board)
        self.assertAlmostEqual(miss, 14 / 15)
        self.assertEqual(dead_types, 14)

    def test_miss_matches_generator_sampling(self):
        board = board_with_middle_row_one_short() | (1 << 60)
        generator = Generator(seed=7)
        samples = 20000
        misses = 0
        for _ in range(samples):
            for piece in generator.next_pieces():
                if not policies._fits(board, piece.index):
                    misses += 1
        miss, _ = policies._fit_profile(board)
        self.assertAlmostEqual(miss, misses / (3 * samples), delta=0.01)


class CompletableTest(unittest.TestCase):
    def test_matches_engine_brute_force(self):
        rng = random.Random(11)
        outcomes = set()
        for density in (0.3, 0.5, 0.6):
            for _ in range(30):
                board = Board()
                board.grid = [[int(rng.random() < density) for _ in range(Board.WIDTH)] for _ in range(Board.HEIGHT)]
                tray = tuple(rng.randrange(len(PIECE_POOL)) for _ in range(3))
                expected = engine_completable(board, [PIECE_POOL[p] for p in tray])
                outcomes.add(expected)
                self.assertEqual(policies._completable(policies._to_bits(board.grid), tray), expected)
        self.assertEqual(outcomes, {True, False})

    def test_stuck_share_matches_engine_on_sampled_trays(self):
        rng = random.Random(13)
        for _ in range(3):
            board = Board()
            board.grid = [[int(rng.random() < 0.6) for _ in range(Board.WIDTH)] for _ in range(Board.HEIGHT)]
            stuck = 0
            for tray in policies.STUCK_TRAYS:
                pieces = [PIECE_POOL[p] for p in tray]
                some_fit = any(
                    board.can_place_piece(piece, x, y)
                    for piece in pieces
                    for y in range(Board.HEIGHT)
                    for x in range(Board.WIDTH)
                )
                if some_fit and not engine_completable(board, pieces):
                    stuck += 1
            self.assertAlmostEqual(policies._stuck_share(policies._to_bits(board.grid)), stuck / len(policies.STUCK_TRAYS))


class RiskTest(unittest.TestCase):
    def test_extremes(self):
        self.assertEqual(policies._risk(0), 0.0)
        full = (1 << 64) - 1
        self.assertAlmostEqual(
            policies._risk(full),
            policies.DEATH_WEIGHT + policies.RISK_LINEAR + policies.RISK_DEAD_TYPE * len(PIECE_TYPES),
        )


class LegalMovesTest(unittest.TestCase):
    def test_policy_returns_available_actions(self):
        policy = policies.build()
        for seed in (1, 2):
            game = Game(seed=seed)
            policy.reset(seed)
            while not game.done and game.placements < 40:
                actions = game.available_actions()
                if not actions:
                    break
                move = policy.act(game, actions)
                self.assertIn(move, actions)
                game.step(move)


if __name__ == "__main__":
    unittest.main()
