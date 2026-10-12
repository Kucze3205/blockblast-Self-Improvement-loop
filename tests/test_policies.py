import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import policies
from board import Board
from game import Game
from pieces import PIECE_POOL

SEED11_BEFORE_PLACEMENT_81 = [
    "..######",
    "#####.##",
    "###.....",
    "..#..###",
    "..##.###",
    "##.#.###",
    "##......",
    "####.###",
]


def game_from(rows, names):
    game = Game(seed=0)
    game.board.grid = [[1 if c == "#" else 0 for c in row] for row in rows]
    by_name = {piece.name: piece for piece in PIECE_POOL}
    game.pieces = [by_name[name] for name in names]
    return game


def max_placements(board, pieces):
    if not pieces:
        return 0
    best = 0
    for i, piece in enumerate(pieces):
        rest = pieces[:i] + pieces[i + 1:]
        for y in range(Board.HEIGHT - len(piece.shape) + 1):
            for x in range(Board.WIDTH - len(piece.shape[0]) + 1):
                if not board.can_place_piece(piece, x, y):
                    continue
                child = board.copy()
                child.place_piece(piece, x, y)
                rows, cols = child.check_full_lines()
                child.clear_lines(rows, cols)
                best = max(best, 1 + max_placements(child, rest))
                if best == len(pieces):
                    return best
    return best


def placements_after(game, move):
    idx, x, y = move
    board = game.board.copy()
    board.place_piece(game.pieces[idx], x, y)
    rows, cols = board.check_full_lines()
    board.clear_lines(rows, cols)
    rest = [p for j, p in enumerate(game.pieces) if p is not None and j != idx]
    return 1 + max_placements(board, rest)


class TestTrayCompletion(unittest.TestCase):
    def test_move_completes_tray_that_beam_misses(self):
        game = game_from(SEED11_BEFORE_PLACEMENT_81, ["1x1", "beam4-1", "beam5-1"])
        self.assertEqual(max_placements(game.board, game.pieces), 3)
        policy = policies.build(None)
        policy.reset(11)
        move = policy.act(game, game.available_actions())
        self.assertEqual(placements_after(game, move), 3)

    def test_move_maximizes_placements_in_full_trays(self):
        policy = policies.build(None)
        checked = 0
        for seed in range(2):
            game = Game(seed=seed)
            policy.reset(seed)
            while checked < 3 and not game.done:
                actions = game.available_actions()
                if not actions:
                    break
                move = policy.act(game, actions)
                if sum(p is not None for p in game.pieces) == 3:
                    best = max(placements_after(game, action) for action in actions)
                    self.assertEqual(placements_after(game, move), best)
                    checked += 1
                game.step(move)
        self.assertEqual(checked, 3)


class TestTrayBeamPolicy(unittest.TestCase):
    def test_build_returns_policy_that_ignores_weights(self):
        game = Game(seed=1)
        actions = game.available_actions()
        for weights in (None, "nieistniejacy/katalog"):
            policy = policies.build(weights)
            policy.reset(0)
            self.assertIn(policy.act(game, actions), actions)

    def test_moves_are_legal_over_short_games(self):
        for seed in range(3):
            policy = policies.build(None)
            policy.reset(seed)
            game = Game(seed=seed)
            for _ in range(60):
                actions = game.available_actions()
                if game.done or not actions:
                    break
                move = policy.act(game, actions)
                self.assertIn(move, actions)
                _, _, _, reason = game.step(move)
                self.assertNotEqual(reason, "wrong_placement")


if __name__ == "__main__":
    unittest.main(verbosity=2)
