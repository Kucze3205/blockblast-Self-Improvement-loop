"""
Testy kontraktu `policies.build` i dokończalności tacki na bitboardzie.

Dokończalność jest sprawdzana względem silnika (board.py), a nie względem samej siebie.
Testy nie mierzą jakości gry.
"""
import os
import random
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from board import Board
from game import Game
from pieces import PIECE_POOL, Piece
from policies import build
from tray_search import completable, from_grid, shape_key


def brute_completable(grid, shapes):
    if not shapes:
        return True
    for i, shape in enumerate(shapes):
        piece = Piece(shape, "ref", -1)
        for y in range(8 - len(shape) + 1):
            for x in range(8 - len(shape[0]) + 1):
                trial = Board()
                trial.grid = [row[:] for row in grid]
                if not trial.place_piece(piece, x, y):
                    continue
                trial.clear_lines(*trial.check_full_lines())
                if brute_completable(trial.grid, shapes[:i] + shapes[i + 1:]):
                    return True
    return False


def random_grid(rng, density):
    return [[int(rng.random() < density) for _ in range(8)] for _ in range(8)]


class CompletableTest(unittest.TestCase):
    def test_matches_engine_on_random_trays(self):
        rng = random.Random(7)
        for _ in range(300):
            grid = random_grid(rng, rng.uniform(0.0, 0.6))
            shapes = [rng.choice(PIECE_POOL).shape for _ in range(rng.randint(1, 3))]
            expected = brute_completable(grid, shapes)
            got = completable(from_grid(grid), [shape_key(s) for s in shapes])
            self.assertEqual(got, expected, (grid, shapes))

    def test_empty_tray_is_completable(self):
        self.assertTrue(completable(0, []))


class BuildPolicyTest(unittest.TestCase):
    def test_plays_legal_moves_in_engine_games(self):
        for seed in range(3):
            game = Game(seed=seed)
            policy = build(None)
            policy.reset(seed)
            for _ in range(150):
                if game.done:
                    break
                actions = game.available_actions()
                if not actions:
                    break
                move = policy.act(game, actions)
                self.assertIn(move, actions)
                _, _, _, reason = game.step(move)
                self.assertNotEqual(reason, "wrong_placement")

    def test_accepts_bridge_namespace(self):
        board = Board()
        pieces = [Piece(PIECE_POOL[0].shape, "slot0", -1), None,
                  Piece(PIECE_POOL[5].shape, "slot2", -1)]
        game = SimpleNamespace(board=board, pieces=pieces, combo=0)
        actions = [(i, x, y) for i, p in enumerate(pieces) if p is not None
                   for y in range(8) for x in range(8) if board.can_place_piece(p, x, y)]
        self.assertIn(build(None).act(game, actions), actions)


if __name__ == "__main__":
    unittest.main()
