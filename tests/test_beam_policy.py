"""Cechy bitowe i kara dopasowania BeamPolicy zgodne z odniesieniem liczonym po komórkach."""
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import policies
from board import Board
from game import Game
from pieces import PIECE_POOL, PIECE_TYPES


def random_grid(rng, density):
    return [[1 if rng.random() < density else 0 for _ in range(8)] for _ in range(8)]


def reference_features(grid):
    def filled(y, x):
        return 0 <= y < 8 and 0 <= x < 8 and grid[y][x] == 1

    occ = sum(sum(row) for row in grid)
    iso = trans = edge = 0
    for y in range(8):
        for x in range(8):
            if grid[y][x] == 0:
                blocked = sum(filled(y + dy, x + dx) for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)))
                if blocked >= 3:
                    iso += 1
                if y in (0, 7) or x in (0, 7):
                    edge += 1
            if x < 7 and grid[y][x] != grid[y][x + 1]:
                trans += 1
            if y < 7 and grid[y][x] != grid[y + 1][x]:
                trans += 1
    return occ, iso, trans, edge


def reference_fit(grid):
    board = Board()
    board.grid = [row[:] for row in grid]
    p = policies.DEFAULT_PARAMS
    shares = []
    dead = 0
    for poses in PIECE_TYPES:
        fitting = sum(
            1
            for pose in poses
            if any(board.can_place_piece(PIECE_POOL[pose], x, y) for y in range(8) for x in range(8))
        )
        shares.append(fitting / len(poses))
        if fitting == 0:
            dead += 1
    alive = [share for share in shares if share > 0]
    mean_alive = sum(alive) / len(alive) if alive else 0.0
    mean_all = sum(shares) / len(shares)
    return p["fit_cube"] * (1 - mean_alive) ** 3 + p["fit_mean"] * (1 - mean_all) + p["dead"] * dead


class BeamPolicyTest(unittest.TestCase):
    def test_features_match_reference(self):
        rng = random.Random(3)
        for _ in range(200):
            grid = random_grid(rng, rng.uniform(0.0, 0.8))
            self.assertEqual(reference_features(grid), policies._features(policies._bits(grid)))

    def test_fit_penalty_matches_reference(self):
        rng = random.Random(6)
        policy = policies.build(None)
        for _ in range(60):
            grid = random_grid(rng, rng.uniform(0.0, 0.8))
            self.assertAlmostEqual(reference_fit(grid), policy._fit_penalty(policies._bits(grid)))

    def test_fits_within_matches_fits_without_budget(self):
        rng = random.Random(9)
        for _ in range(200):
            bits = policies._bits(random_grid(rng, rng.uniform(0.3, 0.9)))
            pieces = [policies._shape_mask(PIECE_POOL[rng.randrange(len(PIECE_POOL))].shape) for _ in range(3)]
            self.assertEqual(policies._fits(bits, pieces), policies._fits_within(bits, pieces, 10**9))

    def test_fits_within_is_optimistic_once_budget_is_spent(self):
        pieces = [policies._shape_mask(PIECE_POOL[0].shape)]
        self.assertTrue(policies._fits_within(0, pieces, 0))

    def test_games_play_legal_moves(self):
        for seed in range(3):
            policy = policies.build(None)
            policy.reset(seed)
            game = Game(seed=seed)
            for _ in range(60):
                actions = game.available_actions()
                if not actions:
                    break
                move = policy.act(game, actions)
                self.assertIn(move, actions)
                _, _, done, message = game.step(move)
                self.assertNotEqual(message, "wrong_placement")
                if done:
                    break


if __name__ == "__main__":
    unittest.main()
