import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from board import Board
from game import Game
from pieces import PIECE_POOL
from policies import build
from tray_search import FULL, _completable, _fits, _place, board_bits


def _engine_completable(board, pieces):
    if not pieces:
        return True
    for k, piece in enumerate(pieces):
        for y in range(Board.HEIGHT):
            for x in range(Board.WIDTH):
                if board.can_place_piece(piece, x, y):
                    trial = board.copy()
                    trial.place_piece(piece, x, y)
                    rows, cols = trial.check_full_lines()
                    trial.clear_lines(rows, cols)
                    if _engine_completable(trial, pieces[:k] + pieces[k + 1:]):
                        return True
    return False


class TraySearchTest(unittest.TestCase):
    def test_place_and_clear_match_board(self):
        rng = random.Random(7)
        for seed in range(5):
            game = Game(seed=seed)
            for _ in range(60):
                actions = game.available_actions()
                if not actions:
                    break
                bb = board_bits(game.board)
                for idx, x, y in actions[:12]:
                    piece = game.pieces[idx]
                    trial = game.board.copy()
                    trial.place_piece(piece, x, y)
                    rows, cols = trial.check_full_lines()
                    trial.clear_lines(rows, cols)
                    got, lines = _place(bb, piece.index, y * 8 + x)
                    self.assertEqual(got, board_bits(trial))
                    self.assertEqual(lines, len(rows) + len(cols))
                game.step(rng.choice(actions))

    def test_fit_anchors_match_board(self):
        for seed in range(3):
            game = Game(seed=seed)
            for _ in range(40):
                actions = game.available_actions()
                if not actions:
                    break
                free = FULL ^ board_bits(game.board)
                for piece in PIECE_POOL[::5]:
                    expected = 0
                    for y in range(8):
                        for x in range(8):
                            if game.board.can_place_piece(piece, x, y):
                                expected |= 1 << (y * 8 + x)
                    self.assertEqual(_fits(free, piece.index), expected)
                game.step(actions[0])

    def test_completable_matches_engine(self):
        rng = random.Random(11)
        outcomes = set()
        for density in (0.2, 0.4, 0.5, 0.6):
            for _ in range(25):
                board = Board()
                board.grid = [[int(rng.random() < density) for _ in range(Board.WIDTH)] for _ in range(Board.HEIGHT)]
                tray = [rng.randrange(len(PIECE_POOL)) for _ in range(3)]
                pieces = [PIECE_POOL[p] for p in tray]
                expected = _engine_completable(board, pieces)
                outcomes.add(expected)
                self.assertEqual(_completable(board_bits(board), tuple(tray)), expected)
        self.assertEqual(outcomes, {True, False})
        for seed in range(3):
            game = Game(seed=seed)
            for _ in range(30):
                actions = game.available_actions()
                if not actions:
                    break
                pieces = [piece for piece in game.pieces if piece is not None]
                tray = tuple(piece.index for piece in pieces)
                self.assertEqual(_completable(board_bits(game.board), tray), _engine_completable(game.board, pieces))
                game.step(actions[0])

    def test_policy_moves_are_legal(self):
        policy = build(None)
        for seed in (1, 2, 3):
            game = Game(seed=seed)
            policy.reset(seed)
            while not game.done and game.placements < 40:
                actions = game.available_actions()
                if not actions:
                    break
                move = policy.act(game, actions)
                self.assertIn(move, actions)
                _, _, _, msg = game.step(move)
                self.assertNotEqual(msg, "wrong_placement")


if __name__ == "__main__":
    unittest.main()
