"""
Testy planera tacki: bitboardy zgodne z Board, układalność tacki zgodna z brute force.
"""
import os
import random
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import planner
from board import Board
from game import Game
from pieces import PIECE_POOL
from policies import build

W, H = Board.WIDTH, Board.HEIGHT


def random_grid(rng):
    while True:
        grid = [[1 if rng.random() < 0.4 else 0 for _ in range(W)] for _ in range(H)]
        if any(0 in row for row in grid):
            return grid


def brute_tray(grid, pieces):
    if not pieces:
        return True
    for k, piece in enumerate(pieces):
        for y in range(H - len(piece.shape) + 1):
            for x in range(W - len(piece.shape[0]) + 1):
                board = Board()
                board.grid = [row[:] for row in grid]
                if board.place_piece(piece, x, y):
                    rows, cols = board.check_full_lines()
                    board.clear_lines(rows, cols)
                    if brute_tray(board.grid, pieces[:k] + pieces[k + 1:]):
                        return True
    return False


class BitboardTests(unittest.TestCase):
    def test_transpose_matches_definition(self):
        rng = random.Random(1)
        for _ in range(300):
            b = rng.getrandbits(64)
            expected = 0
            for r in range(H):
                for c in range(W):
                    if (b >> (W * r + c)) & 1:
                        expected |= 1 << (W * c + r)
            self.assertEqual(planner.transpose(b), expected)

    def test_clear_matches_board(self):
        rng = random.Random(2)
        for _ in range(300):
            grid = [[1 if rng.random() < 0.8 else 0 for _ in range(W)] for _ in range(H)]
            board = Board()
            board.grid = [row[:] for row in grid]
            rows, cols = board.check_full_lines()
            board.clear_lines(rows, cols)
            cleared, lines = planner.clear(planner.to_bits(grid))
            self.assertEqual(cleared, planner.to_bits(board.grid))
            self.assertEqual(lines, len(rows) + len(cols))

    def test_placements_match_board(self):
        rng = random.Random(3)
        for _ in range(50):
            grid = random_grid(rng)
            board = Board()
            board.grid = [row[:] for row in grid]
            bits = planner.to_bits(grid)
            for pose, piece in enumerate(PIECE_POOL):
                legal = {(x, y) for x, y, m in planner.PLACEMENTS[pose] if not (bits & m)}
                expected = {
                    (x, y)
                    for y in range(H - len(piece.shape) + 1)
                    for x in range(W - len(piece.shape[0]) + 1)
                    if board.can_place_piece(piece, x, y)
                }
                self.assertEqual(legal, expected)

    def test_transitions_of_single_cell(self):
        self.assertEqual(planner.trans(1 << (W * 3 + 3)), 4)
        self.assertEqual(planner.trans(0), 0)

    def test_isolated_and_edge_empty_match_definition(self):
        rng = random.Random(6)
        for _ in range(200):
            grid = [[1 if rng.random() < 0.5 else 0 for _ in range(W)] for _ in range(H)]
            isolated = edge = 0
            for y in range(H):
                for x in range(W):
                    if grid[y][x]:
                        continue
                    if y in (0, H - 1) or x in (0, W - 1):
                        edge += 1
                    neighbours = [(y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)]
                    if all(not (0 <= ny < H and 0 <= nx < W) or grid[ny][nx] for ny, nx in neighbours):
                        isolated += 1
            bits = planner.to_bits(grid)
            self.assertEqual(planner.isolated(bits), isolated)
            self.assertEqual(planner.edge_empty(bits), edge)

    def test_tray_placeability_matches_brute_force(self):
        rng = random.Random(4)
        for _ in range(150):
            grid = random_grid(rng)
            poses = tuple(rng.randrange(len(PIECE_POOL)) for _ in range(3))
            fast = planner.places_all(planner.to_bits(grid), poses, [10**9])
            slow = brute_tray(grid, [PIECE_POOL[p] for p in poses])
            self.assertEqual(fast, slow)

    def test_single_risk_bounds(self):
        self.assertEqual(planner.single_risk(0), 0.0)
        self.assertAlmostEqual(sum(planner.POSE_WEIGHT), 1.0)
        only_hole = planner.to_bits([[1] * W for _ in range(H)]) & ~1
        self.assertGreater(planner.single_risk(only_hole), 0.9)


class PlannerTests(unittest.TestCase):
    def test_dedupe_keeps_reachable_leaves_per_first_move(self):
        rng = random.Random(5)
        for _ in range(4):
            board = planner.to_bits(random_grid(rng))
            slots = [(i, rng.randrange(len(PIECE_POOL))) for i in range(3)]
            reachable = {}

            def walk(b, lines, rest, first):
                if not rest:
                    reachable.setdefault(first, set()).add((b, lines))
                    return
                for k, (slot, pose) in enumerate(rest):
                    for x, y, m in planner.PLACEMENTS[pose]:
                        if not b & m:
                            nb, n = planner.clear(b | m)
                            walk(nb, lines + n, rest[:k] + rest[k + 1:], first or (slot, x, y))

            walk(board, 0, tuple(slots), None)
            complete, _ = planner.search(board, slots, beam=10**9)
            got = {}
            for _, nb, _, firsts, total in complete:
                for first in firsts:
                    got.setdefault(first, set()).add((nb, total))
            self.assertEqual(got, reachable)

    def test_death_is_scored_on_best_leaf_per_first_move(self):
        rng = random.Random(0)
        board = planner.to_bits(random_grid(rng))
        slots = [(i, rng.randrange(len(PIECE_POOL))) for i in range(3)]
        complete, _ = planner.search(board, slots)
        best = {}
        for cheap, nb, _, firsts, _ in complete:
            for first in firsts:
                if first not in best or cheap > best[first][0]:
                    best[first] = (cheap, nb)
        self.assertGreater(len(best), planner.FINALISTS)
        expected = {nb for _, nb in best.values()}
        with mock.patch.object(planner, "dead_prob", return_value=0.0) as dead_prob:
            planner.plan_move(board, slots, [], [])
        checked = [call.args[0] for call in dead_prob.call_args_list]
        self.assertEqual(len(checked), planner.FINALISTS)
        self.assertLessEqual(set(checked), expected)

    def test_dead_first_move_never_beats_living_move(self):
        complete = [(-100.0, 0, (), frozenset({(0, 0, 0)}), 0)]
        dead = [(1, 0, 0)]
        with mock.patch.object(planner, "search", return_value=(complete, dead)):
            with mock.patch.object(planner, "dead_prob", return_value=1.0):
                self.assertEqual(planner.plan_move(0, [], [], []), (0, 0, 0))

    def test_hard_fail_weights_sum_to_one_and_full_board_fails_all(self):
        triples = planner.hard_triples(random.Random(5))
        self.assertAlmostEqual(sum(w for _, w in triples), 1.0)
        self.assertAlmostEqual(planner.hard_fail(planner.FULL, triples), 1.0)
        self.assertLess(planner.hard_fail(0, triples), 0.5)

    def test_review_skips_unplaceable_next_trays(self):
        def fake_search(board, slots, beam=planner.BEAM):
            if slots[0][1] == 1:
                return [(-40.0, 0, (), (0, 0, 0), 0), (-60.0, 0, (), (0, 0, 0), 0)], []
            return [], [None]

        with mock.patch.object(planner, "search", side_effect=fake_search):
            self.assertEqual(planner._review(0, [(1, 1, 1), (2, 2, 2)]), -40.0)
            self.assertEqual(planner._review(0, [(2, 2, 2)]), -planner.DEATH_W)

    def test_review_can_reorder_finalists(self):
        complete = [(-90.0, 1, (), frozenset({(0, 0, 0)}), 0), (-100.0, 2, (), frozenset({(1, 0, 0)}), 0)]
        review = {1: -200.0, 2: -50.0}

        def fake_search(board, slots, beam=planner.BEAM):
            if board == 0:
                return complete, []
            return [(review[board], 0, (), (0, 0, 0), 0)], []

        with mock.patch.object(planner, "search", side_effect=fake_search):
            with mock.patch.object(planner, "dead_prob", return_value=0.0):
                self.assertEqual(planner.plan_move(0, [(0, 0)], [(0, 0, 0)], []), (1, 0, 0))

    def test_unfit_piece_freed_by_clear_is_not_death(self):
        grid = [[1] * W for _ in range(H)]
        grid[0][W - 1] = 0
        board = planner.to_bits(grid)
        self.assertEqual(planner.dead_prob(board, [(1, 0, 0)]), 0.0)


class PolicyTests(unittest.TestCase):
    def test_build_plays_legal_moves(self):
        policy = build(None)
        for seed in range(3):
            game = Game(seed=seed)
            policy.reset(seed)
            for _ in range(60):
                actions = game.available_actions()
                if game.done or not actions:
                    break
                move = policy.act(game, actions)
                self.assertIn(move, actions)
                game.step(move)


if __name__ == "__main__":
    unittest.main()
