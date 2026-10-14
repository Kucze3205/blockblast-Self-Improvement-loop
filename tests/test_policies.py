"""Testy polityki survival: interfejs build, zgodność bitboardów z Board, legalna partia."""
import os
import random
import sys
import unittest
from itertools import permutations

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from board import Board
from game import Game
from pieces import PIECE_POOL
import policies
import survival


def random_grid(rng):
    density = rng.uniform(0.3, 0.8)
    while True:
        grid = [[int(rng.random() < density) for _ in range(Board.WIDTH)] for _ in range(Board.HEIGHT)]
        board = Board()
        board.grid = grid
        rows, cols = board.check_full_lines()
        if not rows and not cols:
            return grid


def tray_fits_in_order(grid, pieces):
    if not pieces:
        return True
    for y in range(Board.HEIGHT):
        for x in range(Board.WIDTH):
            board = Board()
            board.grid = [row[:] for row in grid]
            if not board.can_place_piece(pieces[0], x, y):
                continue
            board.place_piece(pieces[0], x, y)
            rows, cols = board.check_full_lines()
            board.clear_lines(rows, cols)
            if tray_fits_in_order(board.grid, pieces[1:]):
                return True
    return False


class BuildTest(unittest.TestCase):
    def test_build_zwraca_polityke_grajaca_legalnie(self):
        policy = policies.build(None)
        self.assertEqual(policy.name, "survival")
        policy.reset(0)
        game = Game(0)
        actions = game.available_actions()
        self.assertIn(policy.act(game, actions), actions)


class BitboardTest(unittest.TestCase):
    def test_prawdopodobienstwa_sumuja_sie_do_jednosci(self):
        self.assertAlmostEqual(sum(survival.POSE_PROB), 1.0)

    def test_ukladalnosc_tacki_zgodna_z_brute_force(self):
        rng = random.Random(11)
        outcomes = set()
        for _ in range(40):
            grid = random_grid(rng)
            bits = survival.to_bits(grid)
            tray = survival._draw_tray(rng)
            expected = any(
                tray_fits_in_order(grid, [tray[i] for i in order]) for order in permutations(range(3))
            )
            self.assertEqual(survival._completable(bits, tray, (0, 1, 2)), expected)
            outcomes.add(expected)
        self.assertEqual(outcomes, {True, False})

    def test_dopasowanie_i_czyszczenie_zgodne_z_Board(self):
        rng = random.Random(7)
        clears = 0
        for _ in range(12):
            grid = random_grid(rng)
            bits = survival.to_bits(grid)
            for p, piece in enumerate(PIECE_POOL):
                for entry in survival.PLACEMENTS[p]:
                    board = Board()
                    board.grid = [row[:] for row in grid]
                    fits = board.place_piece(piece, entry[1], entry[2])
                    self.assertEqual(fits, not bits & entry[0])
                    if not fits:
                        continue
                    rows, cols = board.check_full_lines()
                    board.clear_lines(rows, cols)
                    placed, cleared = survival._place(bits, entry)
                    self.assertEqual(placed, survival.to_bits(board.grid))
                    self.assertEqual(cleared, len(rows) + len(cols))
                    if cleared:
                        clears += 1
        self.assertGreater(clears, 0)


class GameSmokeTest(unittest.TestCase):
    def test_partia_ruchy_legalne(self):
        policy = policies.build(None)
        for seed in range(3):
            game = Game(seed)
            policy.reset(seed)
            for _ in range(30):
                actions = game.available_actions()
                if not actions:
                    break
                action = policy.act(game, actions)
                self.assertIn(action, actions)
                _, _, done, reason = game.step(action)
                self.assertNotEqual(reason, "wrong_placement")
                if done:
                    break


if __name__ == "__main__":
    unittest.main()
