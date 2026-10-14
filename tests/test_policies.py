"""
Testy polityki tacki: kontrakt build/reset/act i pomocnicze operacje na bitboardzie.
"""
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from board import Board
from game import Game
from pieces import PIECE_POOL
from policies import (
    _bits, _clear, _fits, _isolated, _joint_failure, _joint_ok, _transitions, build,
)


class TestTrayPolicyContract(unittest.TestCase):
    def test_build_accepts_missing_weights(self):
        policy = build(None)
        policy.reset(1)
        game = Game(seed=1)
        actions = game.available_actions()
        self.assertIn(policy.act(game, actions), actions)

    def test_plays_only_legal_moves(self):
        policy = build(None)
        for seed in (3, 11):
            game = Game(seed=seed)
            policy.reset(seed)
            for _ in range(60):
                actions = game.available_actions()
                if game.done or not actions:
                    break
                move = policy.act(game, actions)
                self.assertIn(move, actions)
                game.step(move)
            self.assertGreater(game.placements, 0)


class TestBitboardHelpers(unittest.TestCase):
    def test_full_row_is_cleared(self):
        grid = [[1] * 8] + [[0] * 8 for _ in range(7)]
        board, cleared = _clear(_bits(grid))
        self.assertEqual((board, cleared), (0, 1))

    def test_empty_board_has_no_transitions(self):
        self.assertEqual(_transitions(0), 0)

    def test_single_cell_adds_four_transitions(self):
        center = 1 << (8 * 3 + 3)
        self.assertEqual(_transitions(center), 4)

    def test_enclosed_empty_cell_is_isolated(self):
        corner_enclosed = (1 << 1) | (1 << 8)
        self.assertEqual(_isolated(corner_enclosed), 1)


def _placeable(board, piece):
    return any(board.can_place_piece(piece, x, y)
               for y in range(Board.HEIGHT - len(piece.shape) + 1)
               for x in range(Board.WIDTH - len(piece.shape[0]) + 1))


def _reference_ok(board, pieces):
    if not pieces:
        return True
    for index, piece in enumerate(pieces):
        rest = pieces[:index] + pieces[index + 1:]
        for y in range(Board.HEIGHT - len(piece.shape) + 1):
            for x in range(Board.WIDTH - len(piece.shape[0]) + 1):
                if not board.can_place_piece(piece, x, y):
                    continue
                nxt = board.copy()
                nxt.place_piece(piece, x, y)
                rows, cols = nxt.check_full_lines()
                nxt.clear_lines(rows, cols)
                if rest and not any(_placeable(nxt, other) for other in rest):
                    continue
                if _reference_ok(nxt, rest):
                    return True
    return False


def _grid(rows):
    return [[1 if ch == "#" else 0 for ch in row] for row in rows]


def _pose(shape):
    return next(piece.index for piece in PIECE_POOL if piece.shape == shape)


class TestJointPlaceability(unittest.TestCase):
    def test_each_piece_fits_but_two_bars_have_no_second_run(self):
        board = _bits(_grid([
            "#.#..###",
            "#.######",
            "##.#..##",
            "#.####.#",
            "#.####.#",
            ".....#..",
            ".#.###..",
            "#...###.",
        ]))
        vertical3 = _pose([[1], [1], [1]])
        bar4 = _pose([[1, 1, 1, 1]])
        self.assertTrue(all(_fits(board, pose) for pose in (vertical3, bar4)))
        self.assertTrue(_joint_ok(board, (vertical3, bar4), {}))
        self.assertFalse(_joint_ok(board, (vertical3, bar4, bar4), {}))

    def test_tray_with_no_piece_fitting_now_is_counted_dead(self):
        board = _bits(_grid(["#######."] + ["########"] * 7))
        vertical3 = _pose([[1], [1], [1]])
        self.assertEqual(_joint_failure(board, [(vertical3,) * 3], {}), 1.0)

    def test_matches_board_simulation(self):
        rng = random.Random(7)
        for game_seed in range(8):
            game = Game(seed=game_seed)
            for _ in range(rng.randrange(0, 45)):
                actions = game.available_actions()
                if game.done or not actions:
                    break
                game.step(rng.choice(actions))
            board = _bits(game.board.grid)
            for _ in range(60):
                poses = tuple(rng.randrange(len(PIECE_POOL)) for _ in range(3))
                expected = _reference_ok(game.board, [PIECE_POOL[pose] for pose in poses])
                self.assertEqual(_joint_ok(board, poses, {}), expected, poses)


if __name__ == "__main__":
    unittest.main(verbosity=2)
