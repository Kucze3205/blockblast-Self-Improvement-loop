"""Testy polityki wiązkowej: bitboardy zgodne z Board, cechy i wykładalność zgodne z referencją."""
import os
import random
import sys
import unittest
import unittest.mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import policies as pol
from board import Board
from game import Game
from pieces import PIECE_POOL, PIECE_TYPES


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
    def filled(y, x):
        return 0 <= y < 8 and 0 <= x < 8 and grid[y][x] == 1

    occ = sum(sum(row) for row in grid)
    pockets = trans = edge = 0
    for y in range(8):
        for x in range(8):
            if grid[y][x] == 0:
                if sum(filled(y + dy, x + dx) for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1))) >= 3:
                    pockets += 1
                if y in (0, 7) or x in (0, 7):
                    edge += 1
            if x < 7 and grid[y][x] != grid[y][x + 1]:
                trans += 1
            if y < 7 and grid[y][x] != grid[y + 1][x]:
                trans += 1
    return occ, pockets, trans, edge


def reference_fit(grid):
    board = board_from(grid)
    shares = []
    dead = 0
    for poses in PIECE_TYPES:
        fitting = sum(
            1 for pose in poses
            if any(board.can_place_piece(PIECE_POOL[pose], x, y) for y in range(8) for x in range(8))
        )
        shares.append(fitting / len(poses))
        if fitting == 0:
            dead += 1
    alive = [share for share in shares if share > 0]
    mean_alive = sum(alive) / len(alive) if alive else 0.0
    mean_all = sum(shares) / len(shares)
    return pol._FIT_CUBE_W * (1 - mean_alive) ** 3 + pol._FIT_MEAN_W * (1 - mean_all) + pol._DEAD_W * dead


class TrayBeamTest(unittest.TestCase):
    def test_placements_match_board(self):
        rng = random.Random(1)
        for _ in range(20):
            grid = random_grid(rng, rng.uniform(0.1, 0.7))
            board = board_from(grid)
            bits = pol._to_bits(grid)
            for piece in PIECE_POOL:
                ref = {(x, y) for y in range(8) for x in range(8) if board.can_place_piece(piece, x, y)}
                got = {(x, y) for mask, x, y in pol._PLACEMENTS[piece.index] if not (bits & mask)}
                self.assertEqual(ref, got, piece.name)

    def test_clear_matches_board(self):
        rng = random.Random(2)
        for _ in range(200):
            grid = random_grid(rng, 0.85)
            board = board_from(grid)
            rows, cols = board.check_full_lines()
            board.clear_lines(rows, cols)
            bits, cleared = pol._clear(pol._to_bits(grid))
            self.assertEqual(pol._to_bits(board.grid), bits)
            self.assertEqual(len(rows) + len(cols), cleared)

    def test_features_match_reference(self):
        rng = random.Random(3)
        for _ in range(200):
            grid = random_grid(rng, rng.uniform(0.0, 0.8))
            self.assertEqual(reference_features(grid), pol._features(pol._to_bits(grid)))

    def test_fit_penalty_matches_reference(self):
        rng = random.Random(6)
        for _ in range(100):
            grid = random_grid(rng, rng.uniform(0.0, 0.8))
            self.assertAlmostEqual(reference_fit(grid), pol._fit_penalty(pol._to_bits(grid)))

    def test_playable_matches_brute_force(self):
        rng = random.Random(4)
        for _ in range(150):
            grid = random_grid(rng, rng.uniform(0.2, 0.7))
            pieces = [rng.choice(PIECE_POOL) for _ in range(3)]
            expected = brute_playable(grid, pieces)
            got = pol._playable(pol._to_bits(grid), tuple(p.index for p in pieces), [10 ** 9])
            self.assertEqual(expected, got)

    def test_beam_finds_every_completable_first_move(self):
        rng = random.Random(5)
        big = 10 ** 6
        with unittest.mock.patch.object(pol, "_BEAM", big):
            for _ in range(60):
                bits = pol._to_bits(random_grid(rng, rng.uniform(0.1, 0.6)))
                remaining = tuple((i, rng.choice(PIECE_POOL).index) for i in range(3))
                found = {move for _, _, move in pol._leaves(bits, remaining)}
                expected = set()
                for idx, pose in remaining:
                    rest = tuple(p for i, p in remaining if i != idx)
                    for mask, x, y in pol._PLACEMENTS[pose]:
                        if not (bits & mask) and pol._playable(pol._clear(bits | mask)[0], rest, [big]):
                            expected.add((idx, x, y))
                self.assertEqual(expected, found)

    def test_build_contract_and_determinism(self):
        def play(seed, moves):
            policy = pol.build(None)
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
