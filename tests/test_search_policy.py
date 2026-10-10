"""Testy bitowych pomocników polityki wiązkowej względem silnika gry (board.py, game.py)."""
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import search_policy as sp
from board import Board
from game import Game
from pieces import PIECE_POOL
from policies import build


def _random_position(seed, moves):
    rng = random.Random(seed)
    game = Game(seed=seed)
    for _ in range(moves):
        actions = game.available_actions()
        if not actions or game.done:
            break
        game.step(rng.choice(actions))
    return game


def _brute_tray_fits(grid, poses):
    if not poses:
        return True
    for i, p in enumerate(poses):
        rest = poses[:i] + poses[i + 1:]
        piece = PIECE_POOL[p]
        for y in range(8 - len(piece.shape) + 1):
            for x in range(8 - len(piece.shape[0]) + 1):
                board = Board()
                board.grid = [row[:] for row in grid]
                if board.can_place_piece(piece, x, y):
                    board.place_piece(piece, x, y)
                    rows, cols = board.check_full_lines()
                    board.clear_lines(rows, cols)
                    if _brute_tray_fits(board.grid, rest):
                        return True
    return False


class SearchPolicyTests(unittest.TestCase):
    def test_positions_match_engine_legal_moves(self):
        for seed in range(20):
            game = _random_position(seed, moves=seed)
            if game.done:
                continue
            bits = sp._board_bits(game.board.grid)
            legal = set(game.available_actions())
            for s, piece in enumerate(game.pieces):
                if piece is None:
                    continue
                mine = {(s, x, y) for mask, x, y in sp.POSITIONS[piece.index] if (bits & mask) == 0}
                self.assertEqual(mine, {a for a in legal if a[0] == s})

    def test_place_matches_board_clear(self):
        for seed in range(20):
            game = _random_position(seed, moves=seed + 5)
            if game.done:
                continue
            bits = sp._board_bits(game.board.grid)
            for idx, x, y in game.available_actions():
                piece = game.pieces[idx]
                mask = next(m for m, xx, yy in sp.POSITIONS[piece.index] if (xx, yy) == (x, y))
                filled, cleared = sp._place(bits, mask)
                board = Board()
                board.grid = [row[:] for row in game.board.grid]
                board.place_piece(piece, x, y)
                rows, cols = board.check_full_lines()
                board.clear_lines(rows, cols)
                self.assertEqual(filled, sp._board_bits(board.grid))
                self.assertEqual(cleared, len(rows) + len(cols))

    def test_tray_fits_matches_brute_force(self):
        rng = random.Random(11)
        for seed in range(10):
            game = _random_position(seed, moves=seed * 3)
            if game.done:
                continue
            bits = sp._board_bits(game.board.grid)
            for _ in range(4):
                tray = [rng.randrange(len(PIECE_POOL)) for _ in range(3)]
                self.assertEqual(sp._tray_fits(bits, tray), _brute_tray_fits(game.board.grid, tray))

    def test_policy_plays_legal_moves(self):
        policy = build(None)
        game = Game(seed=5)
        policy.reset(5)
        for _ in range(30):
            if game.done:
                break
            actions = game.available_actions()
            if not actions:
                break
            action = policy.act(game, actions)
            self.assertIn(action, actions)
            game.step(action)


if __name__ == "__main__":
    unittest.main()
