import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from board import Board
from bitboard import PLACEMENTS, board_to_bits, fitting_masks, place_and_clear
from pieces import PIECE_POOL


def random_grid(rng, density):
    return [[1 if rng.random() < density else 0 for _ in range(Board.WIDTH)]
            for _ in range(Board.HEIGHT)]


class BitboardMatchesBoard(unittest.TestCase):
    def test_fitting_positions_match_can_place_piece(self):
        rng = random.Random(1)
        for trial in range(60):
            grid = random_grid(rng, density=rng.choice([0.0, 0.3, 0.6, 0.8]))
            board = Board()
            board.grid = grid
            bits = board_to_bits(grid)
            for pose_index, piece in enumerate(PIECE_POOL):
                expected = {(x, y) for x, y, _ in PLACEMENTS[pose_index]
                            if board.can_place_piece(piece, x, y)}
                got = {(x, y) for x, y, mask in PLACEMENTS[pose_index]
                       if not bits & mask}
                self.assertEqual(expected, got, f"pose {pose_index}, trial {trial}")

    def test_place_and_clear_matches_board(self):
        rng = random.Random(2)
        checked = 0
        for trial in range(300):
            grid = random_grid(rng, density=rng.choice([0.5, 0.7, 0.85]))
            board = Board()
            board.grid = grid
            bits = board_to_bits(grid)
            pose_index = rng.randrange(len(PIECE_POOL))
            options = [(x, y, mask) for x, y, mask in PLACEMENTS[pose_index]
                       if not bits & mask]
            if not options:
                continue
            x, y, mask = rng.choice(options)
            ref = board.copy()
            ref.place_piece(PIECE_POOL[pose_index], x, y)
            rows, cols = ref.check_full_lines()
            ref.clear_lines(rows, cols)
            new_bits, lines = place_and_clear(bits, mask)
            self.assertEqual(board_to_bits(ref.grid), new_bits)
            self.assertEqual(len(rows) + len(cols), lines)
            checked += 1
        self.assertGreater(checked, 100)

    def test_fitting_masks_agree_with_positions(self):
        bits = board_to_bits(random_grid(random.Random(3), density=0.4))
        for pose_index in range(len(PIECE_POOL)):
            from_positions = [m for _, _, m in PLACEMENTS[pose_index] if not bits & m]
            self.assertEqual(from_positions, fitting_masks(bits, pose_index))


if __name__ == "__main__":
    unittest.main()
