"""Testy polityki wiązkowej: bitboardy zgodne z Board, wykładalność tacki zgodna z brute force."""
import os
import random
import sys
import unittest
import unittest.mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import search_policy as sp
from board import Board
from game import Game
from pieces import PIECE_POOL
import policies


def random_grid(rng, density):
    return [[1 if rng.random() < density else 0 for _ in range(8)] for _ in range(8)]


def board_from(grid):
    board = Board()
    board.grid = [row[:] for row in grid]
    return board


def brute_playable(grid, pieces):
    def go(board, rest):
        if not rest:
            return True
        for i, piece in enumerate(rest):
            others = rest[:i] + rest[i + 1:]
            for y in range(8 - len(piece.shape) + 1):
                for x in range(8 - len(piece.shape[0]) + 1):
                    if board.can_place_piece(piece, x, y):
                        nxt = board.copy()
                        nxt.place_piece(piece, x, y)
                        rows, cols = nxt.check_full_lines()
                        nxt.clear_lines(rows, cols)
                        if go(nxt, others):
                            return True
        return False

    return go(board_from(grid), pieces)


def reference_features(grid):
    def empty(y, x):
        return 0 <= y < 8 and 0 <= x < 8 and grid[y][x] == 0

    occ = sum(sum(row) for row in grid)
    iso = holes = sq = 0
    for y in range(8):
        for x in range(8):
            if grid[y][x] == 0:
                if not any(empty(y + dy, x + dx) for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                    iso += 1
                if any(grid[yy][x] for yy in range(y)):
                    holes += 1
    for y in range(6):
        for x in range(6):
            if all(grid[y + dy][x + dx] == 0 for dy in range(3) for dx in range(3)):
                sq += 1
    return occ, iso, holes, sq


class SearchPolicyTest(unittest.TestCase):
    def test_placements_match_board(self):
        rng = random.Random(1)
        for _ in range(20):
            grid = random_grid(rng, rng.uniform(0.1, 0.7))
            board = board_from(grid)
            bits = sp.to_bits(grid)
            for piece in PIECE_POOL:
                ref = {(x, y) for y in range(8) for x in range(8) if board.can_place_piece(piece, x, y)}
                got = {(x, y) for mask, x, y in sp.PLACEMENTS[piece.index] if not (bits & mask)}
                self.assertEqual(ref, got, piece.name)

    def test_clear_lines_matches_board(self):
        rng = random.Random(2)
        for _ in range(200):
            grid = random_grid(rng, 0.85)
            board = board_from(grid)
            rows, cols = board.check_full_lines()
            board.clear_lines(rows, cols)
            self.assertEqual(sp.to_bits(board.grid), sp.clear_lines(sp.to_bits(grid)))

    def test_features_match_reference(self):
        rng = random.Random(3)
        for _ in range(200):
            grid = random_grid(rng, rng.uniform(0.0, 0.8))
            self.assertEqual(reference_features(grid), sp.features(sp.to_bits(grid)))

    def test_playable_matches_brute_force(self):
        rng = random.Random(4)
        for _ in range(150):
            grid = random_grid(rng, rng.uniform(0.2, 0.7))
            pieces = [rng.choice(PIECE_POOL) for _ in range(3)]
            expected = brute_playable(grid, pieces)
            got = sp.playable(sp.to_bits(grid), tuple(p.index for p in pieces), [10 ** 9])
            self.assertEqual(expected, got)

    def test_beam_finds_every_completable_first_move(self):
        rng = random.Random(5)
        big = 10 ** 6
        policy = sp.SearchPolicy()
        with unittest.mock.patch.object(sp, "BEAM", big):
            for _ in range(60):
                bits = sp.to_bits(random_grid(rng, rng.uniform(0.1, 0.6)))
                remaining = tuple((i, rng.choice(PIECE_POOL).index) for i in range(3))
                found = {move for _, _, move in policy._leaves(bits, remaining)}
                expected = set()
                for idx, pose in remaining:
                    rest = tuple(p for i, p in remaining if i != idx)
                    for mask, x, y in sp.PLACEMENTS[pose]:
                        if not (bits & mask) and sp.playable(sp.clear_lines(bits | mask), rest, [big]):
                            expected.add((idx, x, y))
                self.assertEqual(expected, found)

    def test_build_contract_and_determinism(self):
        def play(seed, moves):
            policy = policies.build(None)
            policy.reset(seed)
            game = Game(seed=seed)
            trace = []
            for _ in range(moves):
                actions = game.available_actions()
                if not actions:
                    break
                move = policy.act(game, actions)
                self.assertIn(move, actions)
                _, _, done, message = game.step(move)
                self.assertNotEqual(message, "wrong_placement")
                trace.append(move)
                if done:
                    break
            return trace

        self.assertEqual(play(5, 60), play(5, 60))


if __name__ == "__main__":
    unittest.main()
