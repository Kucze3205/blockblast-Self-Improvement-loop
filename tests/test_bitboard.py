import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bitboard
from board import Board
from game import Game
from pieces import PIECE_POOL

SIZE = Board.WIDTH


def random_grids(seed, count):
    rng = random.Random(seed)
    game = Game(seed=seed)
    grids = []
    while len(grids) < count:
        grids.append([row[:] for row in game.board.grid])
        actions = game.available_actions()
        if game.done or not actions:
            game = Game(seed=rng.randrange(10**6))
            continue
        game.step(rng.choice(actions))
    return grids


def board_from(grid):
    board = Board()
    board.grid = [row[:] for row in grid]
    return board


class TestFitMasks(unittest.TestCase):
    def test_masks_match_can_place_piece(self):
        for grid in random_grids(seed=1, count=40):
            board = board_from(grid)
            masks = bitboard.fit_masks(bitboard.occupancy(grid))
            for pose, piece in enumerate(PIECE_POOL):
                for y in range(SIZE):
                    for x in range(SIZE):
                        bit = (masks[pose] >> (y * SIZE + x)) & 1
                        self.assertEqual(bool(bit), board.can_place_piece(piece, x, y))

    def test_empty_board_fits_every_pose(self):
        fit, _ = bitboard.fit_stats(bitboard.fit_masks(0))
        self.assertAlmostEqual(fit, 1.0)

    def test_fit_stats_match_brute_force(self):
        for grid in random_grids(seed=3, count=40):
            board = board_from(grid)
            fit, places = bitboard.fit_stats(bitboard.fit_masks(bitboard.occupancy(grid)))
            brute_fit = brute_places = 0.0
            for pose, piece in enumerate(PIECE_POOL):
                count = sum(board.can_place_piece(piece, x, y) for y in range(SIZE) for x in range(SIZE))
                if count:
                    brute_fit += bitboard.POSE_PROB[pose]
                brute_places += bitboard.POSE_PROB[pose] * count
            self.assertAlmostEqual(fit, brute_fit)
            self.assertAlmostEqual(places, brute_places)

    def test_pose_probabilities_sum_to_one(self):
        self.assertAlmostEqual(sum(bitboard.POSE_PROB), 1.0)


class TestPlace(unittest.TestCase):
    def test_place_matches_board_including_line_clears(self):
        rng = random.Random(7)
        for grid in random_grids(seed=2, count=40):
            board = board_from(grid)
            occupied = bitboard.occupancy(grid)
            for pose, piece in enumerate(PIECE_POOL):
                anchors = [(x, y) for y in range(SIZE) for x in range(SIZE) if board.can_place_piece(piece, x, y)]
                if not anchors:
                    continue
                x, y = rng.choice(anchors)
                after = board_from(grid)
                after.place_piece(piece, x, y)
                rows, cols = after.check_full_lines()
                after.clear_lines(rows, cols)
                new_occupied, lines = bitboard.place(occupied, pose, x, y)
                self.assertEqual(new_occupied, bitboard.occupancy(after.grid))
                self.assertEqual(lines, len(rows) + len(cols))


if __name__ == "__main__":
    unittest.main(verbosity=2)
