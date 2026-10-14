"""
Testy polityki przeżycia: kontrakt z ewaluatorem, legalność ruchów i zgodność
bitboardów z symulatorem Board.
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
    BOUNDARY_WEIGHT,
    FINALISTS,
    ISOLATED_WEIGHT,
    TRANSITION_WEIGHT,
    _fit_penalty,
    _place_and_clear,
    _placements,
    _plan_values,
    _pocket_cells,
    _sample_tray,
    _structure_cost,
    _stuck_share,
    _to_bits,
    _tray_playable,
    build,
)

FULL = (1 << 64) - 1


def random_board(rng, fill):
    board = Board()
    for y in range(Board.HEIGHT):
        for x in range(Board.WIDTH):
            if rng.random() < fill:
                board.grid[y][x] = 1
    return board


def naive_structure_cost(grid):
    isolated = transitions = boundary = 0
    for y in range(8):
        for x in range(8):
            if not grid[y][x]:
                if x in (0, 7) or y in (0, 7):
                    boundary += 1
                neighbours = [
                    grid[y + dy][x + dx]
                    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                    if 0 <= x + dx < 8 and 0 <= y + dy < 8
                ]
                if all(neighbours):
                    isolated += 1
            if x < 7:
                transitions += grid[y][x] != grid[y][x + 1]
            if y < 7:
                transitions += grid[y][x] != grid[y + 1][x]
    return ISOLATED_WEIGHT * isolated + TRANSITION_WEIGHT * transitions + BOUNDARY_WEIGHT * boundary


def playable_on_board(board, pieces):
    """Wzorzec: przeszukanie kolejności kładzenia tacki na symulatorze."""
    if not pieces:
        return True
    for i, piece in enumerate(pieces):
        rest = pieces[:i] + pieces[i + 1:]
        for y in range(Board.HEIGHT - len(piece.shape) + 1):
            for x in range(Board.WIDTH - len(piece.shape[0]) + 1):
                if board.can_place_piece(piece, x, y):
                    nxt = board.copy()
                    nxt.place_piece(piece, x, y)
                    rows, cols = nxt.check_full_lines()
                    nxt.clear_lines(rows, cols)
                    if playable_on_board(nxt, rest):
                        return True
    return False


class BitboardTest(unittest.TestCase):
    def test_masks_agree_with_board_legality(self):
        rng = random.Random(1)
        for _ in range(3):
            board = random_board(rng, 0.4)
            bits = _to_bits(board.grid)
            for piece in PIECE_POOL:
                for (x, y), mask in _placements(piece).items():
                    self.assertEqual(board.can_place_piece(piece, x, y), not (bits & mask))

    def test_clears_agree_with_board(self):
        rng = random.Random(2)
        for _ in range(3):
            board = random_board(rng, 0.6)
            bits = _to_bits(board.grid)
            for piece in PIECE_POOL:
                for (x, y), mask in _placements(piece).items():
                    if not board.can_place_piece(piece, x, y):
                        continue
                    nxt = board.copy()
                    nxt.place_piece(piece, x, y)
                    rows, cols = nxt.check_full_lines()
                    nxt.clear_lines(rows, cols)
                    after, lines = _place_and_clear(bits, mask)
                    self.assertEqual(after, _to_bits(nxt.grid))
                    self.assertEqual(lines, len(rows) + len(cols))

    def test_pocket_cells_counts_only_regions_below_three(self):
        self.assertEqual(_pocket_cells(0), 0)
        self.assertEqual(_pocket_cells(FULL & ~0b11), 2)
        self.assertEqual(_pocket_cells(FULL & ~0b111), 0)


class StructureTest(unittest.TestCase):
    def test_structure_cost_matches_naive_count(self):
        rng = random.Random(5)
        for _ in range(5):
            board = random_board(rng, 0.45)
            self.assertAlmostEqual(
                _structure_cost(_to_bits(board.grid)),
                naive_structure_cost(board.grid),
            )

    def test_fit_penalty_is_zero_on_empty_board_and_positive_on_full_board(self):
        self.assertEqual(_fit_penalty(0), 0)
        self.assertGreater(_fit_penalty(FULL), 0)


class TrayPlayableTest(unittest.TestCase):
    def test_agrees_with_board_search(self):
        rng = random.Random(3)
        for _ in range(10):
            board = random_board(rng, 0.35)
            pieces = [rng.choice(PIECE_POOL) for _ in range(rng.randint(1, 3))]
            self.assertEqual(
                _tray_playable(_to_bits(board.grid), pieces),
                playable_on_board(board, pieces),
            )

    def test_piece_order_does_not_matter(self):
        h3 = next(p for p in PIECE_POOL if p.shape == [[1, 1, 1]])
        h2 = next(p for p in PIECE_POOL if p.shape == [[1, 1]])
        # Najpierw H2 domyka wiersz 0 i zwalnia miejsce dla H3, którego przed tym nie ma.
        grid = [[0 if x < 2 and y in (0, 7) else 1 for x in range(8)] for y in range(8)]
        self.assertTrue(_tray_playable(_to_bits(grid), [h3, h2]))


class TrayBeamPolicyTest(unittest.TestCase):
    def test_plan_values_name_only_legal_actions(self):
        rng = random.Random(6)
        for seed in range(4):
            game = Game(seed)
            game.board.grid = random_board(rng, 0.3).grid
            samples = [_sample_tray(rng) for _ in range(16)]
            values = _plan_values(_to_bits(game.board.grid), list(game.pieces), samples)
            self.assertTrue(set(values) <= set(game.available_actions()))

    def test_finalists_are_bounded_by_finalist_count(self):
        rng = random.Random(8)
        tray = [PIECE_POOL[0]] * 3
        samples = [_sample_tray(rng) for _ in range(16)]
        values = _plan_values(0, tray, samples)
        self.assertLessEqual(len(values), FINALISTS)

    def test_stuck_share_is_zero_on_empty_board(self):
        rng = random.Random(7)
        samples = [_sample_tray(rng) for _ in range(64)]
        self.assertEqual(_stuck_share(0, samples), 0)

    def test_build_returns_policy_that_picks_a_legal_action(self):
        policy = build(None)
        policy.reset(0)
        game = Game(0)
        actions = game.available_actions()
        self.assertIn(policy.act(game, actions), actions)

    def test_same_seed_same_moves(self):
        def play(seed):
            game, policy = Game(seed), build(None)
            policy.reset(seed)
            moves = []
            while not game.done and game.placements < 30:
                actions = game.available_actions()
                if not actions:
                    break
                move = policy.act(game, actions)
                moves.append(move)
                game.step(move)
            return moves

        self.assertEqual(play(7), play(7))

    def test_no_wrong_placements_over_short_games(self):
        for seed in range(3):
            game, policy = Game(seed), build(None)
            policy.reset(seed)
            while not game.done and game.placements < 30:
                actions = game.available_actions()
                if not actions:
                    break
                _, _, _, message = game.step(policy.act(game, actions))
                self.assertNotEqual(message, "wrong_placement")

    def test_chosen_move_keeps_tray_playable_when_some_move_does(self):
        rng = random.Random(4)
        policy = build(None)
        policy.reset(0)
        for _ in range(4):
            game = Game(rng.randrange(1000))
            game.board.grid = random_board(rng, 0.35).grid
            game.pieces = [rng.choice(PIECE_POOL) for _ in range(3)]
            actions = game.available_actions()
            if not actions:
                continue
            kept = {}
            for action in actions:
                idx, x, y = action
                nxt = game.board.copy()
                nxt.place_piece(game.pieces[idx], x, y)
                rows, cols = nxt.check_full_lines()
                nxt.clear_lines(rows, cols)
                rest = [p for j, p in enumerate(game.pieces) if j != idx]
                kept[action] = playable_on_board(nxt, rest)
            chosen = policy.act(game, actions)
            if any(kept.values()):
                self.assertTrue(kept[chosen])


if __name__ == "__main__":
    unittest.main()
