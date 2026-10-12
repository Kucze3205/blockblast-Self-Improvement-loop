import os
import random
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bitboard
import policies
from board import Board
from game import Game
from generator import Generator
from pieces import PIECE_POOL, Piece

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


class TestPlacements(unittest.TestCase):
    def test_placements_match_can_place_piece_and_mask(self):
        rng = random.Random(5)
        for _ in range(10):
            board = Board()
            board.grid = [[int(rng.random() < 0.4) for _ in range(8)] for _ in range(8)]
            bits = bitboard.occupancy(board.grid)
            for piece in PIECE_POOL:
                legal = {(x, y) for y in range(8) for x in range(8) if board.can_place_piece(piece, x, y)}
                fitted = set()
                for x, y, mask in policies._placements(piece.shape):
                    if (bits & mask) == 0:
                        fitted.add((x, y))
                    if (x, y) in legal:
                        after = board.copy()
                        after.place_piece(piece, x, y)
                        self.assertEqual(bitboard.occupancy(after.grid), bits | mask)
                self.assertEqual(fitted, legal)


class TestTraySearchPolicy(unittest.TestCase):
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

    def test_accepts_pieces_without_pool_index(self):
        board = Board()
        board.grid[7][0] = 1
        pieces = [Piece([[1, 1, 1]], "bridge", -1), None, Piece([[1], [1]], "bridge", -1)]
        actions = [(i, x, y) for i, p in enumerate(pieces) if p is not None
                   for y in range(8) for x in range(8) if board.can_place_piece(p, x, y)]
        game = SimpleNamespace(board=board, pieces=pieces, combo=0)
        self.assertIn(policies.build(None).act(game, actions), actions)


class TestTrayReview(unittest.TestCase):
    def test_review_skips_unplaceable_trays(self):
        grid = [[1] * 8 for _ in range(8)]
        for x in range(3):
            grid[0][x] = 0
        board = bitboard.occupancy(grid)
        fits = [Piece([[1]], "bridge", -1)] * 3
        square = [Piece([[1, 1], [1, 1]], "bridge", -1)] * 3
        self.assertEqual(policies._review(board, [square, fits]), policies._review(board, [fits]))
        self.assertEqual(policies._review(board, [square]), -policies.TRAY_FAIL)


class TestReviewDraws(unittest.TestCase):
    def test_same_seed_plays_same_game(self):
        def play(seed):
            policy = policies.build(None)
            policy.reset(seed)
            game = Game(seed=seed)
            moves = []
            for _ in range(40):
                actions = game.available_actions()
                if game.done or not actions:
                    break
                move = policy.act(game, actions)
                moves.append(move)
                game.step(move)
            return moves

        self.assertEqual(play(4), play(4))

    def test_review_draws_differ_from_game_stream(self):
        policy = policies.build(None)
        policy.reset(7)
        reviewed = [[p.name for p in policy._draws.next_pieces()] for _ in range(2)]
        generator = Generator(7)
        game = [[p.name for p in generator.next_pieces()] for _ in range(2)]
        self.assertNotEqual(reviewed, game)


class TestTail(unittest.TestCase):
    def setUp(self):
        self.by_name = {piece.name: piece for piece in PIECE_POOL}
        self.checker = bitboard.occupancy([[1 if (x + y) % 2 else 0 for x in range(8)] for y in range(8)])

    def test_completable_needs_room_for_every_piece(self):
        single = policies._placements(self.by_name["1x1"].shape)
        square = policies._placements(self.by_name["square2"].shape)
        self.assertTrue(policies._completable(self.checker, [single, single, single]))
        self.assertFalse(policies._completable(self.checker, [square]))

    def test_dead_share_counts_unplaceable_trays(self):
        ok = [self.by_name["1x1"]] * 3
        dead = [self.by_name["square2"]] * 3
        self.assertEqual(policies._dead_share(self.checker, [ok, dead]), 0.5)
        self.assertEqual(policies._dead_share(self.checker, []), 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
