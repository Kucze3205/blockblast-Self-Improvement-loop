import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from board import Board
from pieces import PIECE_POOL, PIECE_TYPES
from policies import _completable, _occupancy


def _completable_by_engine(board, pieces):
    if not pieces:
        return True
    for i, piece in enumerate(pieces):
        rest = pieces[:i] + pieces[i + 1:]
        for y in range(Board.HEIGHT - len(piece.shape) + 1):
            for x in range(Board.WIDTH - len(piece.shape[0]) + 1):
                if not board.can_place_piece(piece, x, y):
                    continue
                after = board.copy()
                after.place_piece(piece, x, y)
                rows, cols = after.check_full_lines()
                after.clear_lines(rows, cols)
                if _completable_by_engine(after, rest):
                    return True
    return False


class TestTrayCompletable(unittest.TestCase):
    def test_matches_engine_on_random_boards(self):
        rng = random.Random(7)
        outcomes = set()
        for _ in range(300):
            density = rng.uniform(0.0, 0.7)
            board = Board()
            board.grid = [
                [int(rng.random() < density) for _ in range(Board.WIDTH)]
                for _ in range(Board.HEIGHT)
            ]
            poses = tuple(rng.choice(rng.choice(PIECE_TYPES)) for _ in range(3))
            expected = _completable_by_engine(board, [PIECE_POOL[p] for p in poses])
            outcomes.add(expected)
            self.assertEqual(
                _completable(_occupancy(board), poses),
                expected,
                msg=f"poses={poses} grid={board.grid}",
            )
        self.assertEqual(outcomes, {True, False})


if __name__ == "__main__":
    unittest.main()
