import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from board import Board
from bitboard import board_to_bits
from game import Game
from pieces import PIECE_POOL, PIECE_TYPES
from policies import build
from tray_search import (EDGE_W, ISO_W, LINE_W, OCC_W, TRANS_W, TraySearchPolicy, _completable,
                         _draw_samples, _leaf, _pool, _search)


def brute_completable(board, pieces):
    if not pieces:
        return True
    for k, piece in enumerate(pieces):
        left = pieces[:k] + pieces[k + 1:]
        for x in range(Board.WIDTH):
            for y in range(Board.HEIGHT):
                if board.can_place_piece(piece, x, y):
                    nxt = board.copy()
                    nxt.place_piece(piece, x, y)
                    rows, cols = nxt.check_full_lines()
                    nxt.clear_lines(rows, cols)
                    if brute_completable(nxt, left):
                        return True
    return False


def reference_leaf(grid, lines):
    occupied = sum(cell for row in grid for cell in row)
    isolated = empty_border = 0
    for y in range(8):
        for x in range(8):
            if grid[y][x]:
                continue
            if x in (0, 7) or y in (0, 7):
                empty_border += 1
            open_neighbour = any(
                0 <= nx < 8 and 0 <= ny < 8 and not grid[ny][nx]
                for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)))
            isolated += not open_neighbour
    transitions = sum(grid[y][x] != grid[y][x + 1] for y in range(8) for x in range(7))
    transitions += sum(grid[y][x] != grid[y + 1][x] for y in range(7) for x in range(8))
    return (LINE_W * lines - OCC_W * occupied - ISO_W * isolated
            - TRANS_W * transitions - EDGE_W * empty_border)


class LeafMatchesReference(unittest.TestCase):
    def test_empty_board_scores_only_the_border(self):
        self.assertEqual(-56, _leaf(0, 0))

    def test_matches_grid_count_on_random_boards(self):
        rng = random.Random(11)
        for _ in range(200):
            density = rng.choice([0.0, 0.3, 0.5, 0.8])
            grid = [[1 if rng.random() < density else 0 for _ in range(8)] for _ in range(8)]
            lines = rng.randrange(4)
            self.assertAlmostEqual(reference_leaf(grid, lines), _leaf(board_to_bits(grid), lines))


class CompletabilityMatchesBoard(unittest.TestCase):
    def test_matches_brute_force_on_random_boards(self):
        rng = random.Random(7)
        seen_true = seen_false = 0
        for _ in range(120):
            density = rng.choice([0.3, 0.5, 0.65])
            board = Board()
            board.grid = [[1 if rng.random() < density else 0 for _ in range(8)]
                          for _ in range(8)]
            poses = tuple(rng.choice(rng.choice(PIECE_TYPES)) for _ in range(3))
            expected = brute_completable(board, [PIECE_POOL[p] for p in poses])
            self.assertEqual(expected, _completable(board_to_bits(board.grid), poses))
            seen_true += expected
            seen_false += not expected
        self.assertGreater(seen_true, 10)
        self.assertGreater(seen_false, 10)


class PolicyPlaysLegally(unittest.TestCase):
    def play(self, seed, steps):
        game = Game(seed)
        policy = build(None)
        policy.reset(seed)
        chosen = []
        for _ in range(steps):
            if game.done:
                break
            actions = game.available_actions()
            if not actions:
                break
            action = policy.act(game, actions)
            self.assertIn(action, actions)
            _, _, _, message = game.step(action)
            self.assertNotEqual(message, "wrong_placement")
            chosen.append(action)
        return chosen

    def test_actions_are_legal_on_real_games(self):
        for seed in (1, 2, 3):
            self.play(seed, steps=120)

    def test_same_seed_gives_same_moves(self):
        self.assertEqual(self.play(5, steps=60), self.play(5, steps=60))

    def test_build_returns_policy_with_reset_and_act(self):
        policy = build(None)
        self.assertIsInstance(policy, TraySearchPolicy)
        self.assertTrue(callable(policy.reset) and callable(policy.act))


class RowClearIsNotPenalized(unittest.TestCase):
    def test_piece_completing_bottom_row_is_chosen(self):
        board = Board()
        board.grid[7] = [1, 1, 1, 0, 1, 1, 1, 1]
        pending = ((0, PIECE_TYPES[0][0]),)
        action = _search(board_to_bits(board.grid), pending, _draw_samples("row-clear"))
        self.assertEqual((0, 3, 7), action)

    def test_pool_keeps_best_line_clearing_finalist_outside_top_size(self):
        finals = {
            1: (5.0, (0, 0, 0), 0),
            2: (4.0, (0, 1, 0), 0),
            3: (3.0, (0, 2, 0), 0),
            4: (-9.0, (0, 3, 3), 1),
        }
        self.assertIn(4, _pool(finals, 2))


if __name__ == "__main__":
    unittest.main()
