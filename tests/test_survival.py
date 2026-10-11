import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import policies  # noqa: E402
from bitboard import POSES, fit_mask, line_clear  # noqa: E402
from board import Board  # noqa: E402
from game import Game  # noqa: E402
from pieces import PIECE_POOL  # noqa: E402
from survival import SurvivalPolicy, _occupancy  # noqa: E402


def _random_board(rng, fill):
    board = Board()
    for y in range(Board.HEIGHT):
        for x in range(Board.WIDTH):
            board.grid[y][x] = 1 if rng.random() < fill else 0
    return board


class BitboardTest(unittest.TestCase):
    def test_fit_mask_matches_board_can_place(self):
        rng = random.Random(1)
        for _ in range(60):
            board = _random_board(rng, 0.4)
            occ = _occupancy(board.grid)
            for piece in PIECE_POOL:
                mask = fit_mask(occ, POSES[piece.index])
                expected = {
                    y * 8 + x
                    for y in range(Board.HEIGHT)
                    for x in range(Board.WIDTH)
                    if board.can_place_piece(piece, x, y)
                }
                got = {bit for bit in range(64) if mask >> bit & 1}
                self.assertEqual(got, expected, piece.name)

    def test_line_clear_matches_board(self):
        rng = random.Random(2)
        for _ in range(300):
            board = _random_board(rng, 0.8)
            occ = _occupancy(board.grid)
            rows, cols = board.check_full_lines()
            board.clear_lines(rows, cols)
            new_occ, lines = line_clear(occ)
            self.assertEqual(new_occ, _occupancy(board.grid))
            self.assertEqual(lines, len(rows) + len(cols))


class SurvivalPolicyTest(unittest.TestCase):
    def test_actions_are_legal_and_reproducible(self):
        for seed in range(3):
            runs = []
            for _ in range(2):
                game = Game(seed)
                policy = SurvivalPolicy()
                policy.reset(seed)
                played = []
                for _ in range(80):
                    actions = game.available_actions()
                    if not actions:
                        break
                    action = policy.act(game, actions)
                    self.assertIn(action, actions)
                    played.append(action)
                    if game.step(action)[2]:
                        break
                runs.append(played)
            self.assertEqual(runs[0], runs[1])

    def test_build_returns_policy_with_contract(self):
        game = Game(0)
        policy = policies.build(None)
        policy.reset(0)
        actions = game.available_actions()
        self.assertIn(policy.act(game, actions), actions)


if __name__ == "__main__":
    unittest.main()
