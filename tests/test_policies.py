"""Polityka po tacce: człony liścia i układalność tacki zgodne z wersjami referencyjnymi."""
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import policies
from board import Board
from game import Game
from pieces import PIECE_POOL, PIECE_TYPES

W = policies.W


def _cell(occ, x, y):
    return (occ >> (W * y + x)) & 1


def _naive_isolated(occ):
    count = 0
    for y in range(W):
        for x in range(W):
            if _cell(occ, x, y):
                continue
            neighbours = [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]
            if not any(0 <= a < W and 0 <= b < W and not _cell(occ, a, b) for a, b in neighbours):
                count += 1
    return count


def _naive_cheap(occ, cleared):
    occupied = sum(_cell(occ, x, y) for y in range(W) for x in range(W))
    edge = sum(
        1 for y in range(W) for x in range(W)
        if not _cell(occ, x, y) and (x in (0, W - 1) or y in (0, W - 1))
    )
    transitions = 0
    for y in range(W):
        for x in range(W):
            if x + 1 < W and _cell(occ, x, y) != _cell(occ, x + 1, y):
                transitions += 1
            if y + 1 < W and _cell(occ, x, y) != _cell(occ, x, y + 1):
                transitions += 1
    return (
        policies.W_CLEAR * cleared
        - policies.W_CELLS * occupied
        - policies.W_ISOLATED * _naive_isolated(occ)
        - policies.W_EDGE * edge
        - policies.W_TRANS * transitions
    )


def _engine_completable(board, pieces):
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
                if _engine_completable(after, rest):
                    return True
    return False


class TrayPolicyLeafTest(unittest.TestCase):
    def test_bit_terms_match_cell_by_cell_on_random_boards(self):
        rng = random.Random(1)
        for _ in range(500):
            p = rng.random()
            occ = sum(1 << b for b in range(W * W) if rng.random() < p)
            cleared = rng.randrange(4)
            self.assertEqual(policies._isolated(occ), _naive_isolated(occ))
            self.assertAlmostEqual(policies._cheap(occ, cleared), _naive_cheap(occ, cleared))

    def test_enclosed_hole_is_isolated(self):
        self.assertEqual(policies._isolated(policies.FULL ^ 1), 1)
        self.assertEqual(policies._isolated(0), 0)

    def test_completable_matches_engine_on_random_boards(self):
        rng = random.Random(7)
        outcomes = set()
        for seed in range(10):
            game = Game(seed)
            for _ in range(rng.randrange(0, 60)):
                actions = game.available_actions()
                if not actions:
                    break
                _, _, done, _ = game.step(rng.choice(actions))
                if done:
                    break
            occ = policies._occupancy(game.board.grid)
            for _ in range(3):
                ids = tuple(rng.choice(rng.choice(PIECE_TYPES)) for _ in range(3))
                expected = _engine_completable(game.board, [PIECE_POOL[i] for i in ids])
                outcomes.add(expected)
                self.assertEqual(policies._completes(occ, ids), expected)
        self.assertEqual(outcomes, {True, False})

    def test_moves_are_legal(self):
        policy = policies.build(None)
        for seed in range(2):
            game = Game(seed)
            policy.reset(seed)
            for _ in range(30):
                actions = game.available_actions()
                if not actions:
                    break
                move = policy.act(game, actions)
                self.assertIn(move, actions)
                _, _, done, info = game.step(move)
                self.assertNotEqual(info, "wrong_placement")
                if done:
                    break


if __name__ == "__main__":
    unittest.main()
