import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import bitboard as bb
from board import Board
from pieces import PIECE_POOL


def _random_grid(rng, density):
    return [[1 if rng.random() < density else 0 for _ in range(Board.WIDTH)] for _ in range(Board.HEIGHT)]


class TestBitboard(unittest.TestCase):
    def test_fit_matches_board_anchors(self):
        rng = random.Random(7)
        for _ in range(120):
            grid = _random_grid(rng, rng.choice((0.2, 0.4, 0.6)))
            board = Board()
            board.grid = grid
            free = bb.FULL & ~bb.to_mask(grid)
            for piece in PIECE_POOL:
                expected = set()
                for y in range(Board.HEIGHT - len(piece.shape) + 1):
                    for x in range(Board.WIDTH - len(piece.shape[0]) + 1):
                        if board.can_place_piece(piece, x, y):
                            expected.add(y * Board.WIDTH + x)
                got = set(bb.bits(bb.fit(bb.POSES[piece.index], free)))
                self.assertEqual(got, expected, piece.name)

    def test_place_matches_board(self):
        rng = random.Random(11)
        for _ in range(60):
            grid = _random_grid(rng, 0.3)
            occ = bb.to_mask(grid)
            free = bb.FULL & ~occ
            piece = rng.choice(PIECE_POOL)
            for anchor in bb.bits(bb.fit(bb.POSES[piece.index], free)):
                board = Board()
                board.grid = [row[:] for row in grid]
                x, y = anchor % Board.WIDTH, anchor // Board.WIDTH
                self.assertTrue(board.place_piece(piece, x, y))
                self.assertEqual(bb.to_mask(board.grid), bb.place(occ, bb.POSES[piece.index], anchor))

    def test_clear_matches_board(self):
        rng = random.Random(13)
        for _ in range(200):
            grid = _random_grid(rng, rng.choice((0.5, 0.8, 0.9)))
            board = Board()
            board.grid = [row[:] for row in grid]
            rows, cols = board.check_full_lines()
            board.clear_lines(rows, cols)
            cleared, lines = bb.clear_full(bb.to_mask(grid))
            self.assertEqual(cleared, bb.to_mask(board.grid))
            self.assertEqual(lines, len(rows) + len(cols))


if __name__ == "__main__":
    unittest.main(verbosity=2)
