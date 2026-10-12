"""
Block Blast Engine Test Suite

Testy pilnują kalibracji pod wzór referencyjny z badania #2. Każdy test, który
sprawdza liczbę, jest przywiązany do konkretnej rozbieżności (R-1..R-10), żeby
regresja wskazywała, co dokładnie się rozjechało.
"""
import os
import random
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import policies
from board import Board
from game import Game
from generator import Generator
from pieces import CANONICAL_TYPES, EXPECTED_POSES, PIECE_POOL, PIECE_TYPES, Piece
from scoring import FULL_CLEAR_BONUS, clear_points, line_bonus, placement_points

ONE_BY_ONE = PIECE_POOL[0]


def row_full_except(game, x, filler=False):
    """Plansza z wierszem 0 pełnym poza kolumną x — jedno postawienie czyści jedną linię.

    `filler` zostawia komórkę poza wierszem 0, żeby plansza nie zrobiła się pusta
    i nie doliczył się bonus za pełne czyszczenie (osobny test).
    """
    game.board.grid = [[0] * 8 for _ in range(8)]
    for col in range(8):
        game.board.grid[0][col] = 1
    game.board.grid[0][x] = 0
    if filler:
        game.board.grid[7][0] = 1


def place_1x1(game, x, y):
    game.pieces = [ONE_BY_ONE, None, None]
    game.round_placement = 2  # kolejne postawienie domyka tackę
    game.board.place_piece(ONE_BY_ONE, x, y)
    return game.apply_placement(0)


class TestScoringFormula(unittest.TestCase):
    """R-1: bonus bazowy to 10*l*(l-1), a nie 10*k^2."""

    def test_placement_points_are_cell_count(self):
        for piece in PIECE_POOL:
            cells = sum(sum(row) for row in piece.shape)
            self.assertEqual(placement_points(piece), cells)

    def test_line_bonus_matches_reference(self):
        self.assertEqual(line_bonus(0), 0)
        self.assertEqual(line_bonus(1), 10)
        self.assertEqual(line_bonus(2), 20)
        self.assertEqual(line_bonus(3), 60)

    def test_five_and_six_lines_give_the_two_repeated_numbers(self):
        # 200 i 300 to jedyne dwie liczby, które poradniki powtarzają niezależnie.
        self.assertEqual(line_bonus(5), 200)
        self.assertEqual(line_bonus(6), 300)

    def test_combo_multiplies_the_bonus(self):
        # R-2: combo jest mnożnikiem całego bonusu, nie dodatkiem.
        self.assertEqual(clear_points(1, 2), 20)
        self.assertEqual(clear_points(3, 2), 60)
        self.assertEqual(clear_points(0, 2), 0)


class TestComboMechanics(unittest.TestCase):
    def setUp(self):
        self.game = Game(seed=42)

    def test_combo_rises_per_placement_not_per_tray(self):
        # R-3: combo aktualizuje się po każdym postawieniu.
        row_full_except(self.game, 7, filler=True)
        gained = place_1x1(self.game, 7, 0)
        self.assertEqual(self.game.combo, 1)
        self.assertEqual(gained, 1 + 1 * 10)

        row_full_except(self.game, 7, filler=True)
        gained = place_1x1(self.game, 7, 0)
        self.assertEqual(self.game.combo, 2)
        self.assertEqual(gained, 1 + 2 * 10)

    def test_combo_survives_two_placements_then_dies(self):
        # R-4: combo wygasa przez licznik, nie natychmiast.
        row_full_except(self.game, 7, filler=True)
        place_1x1(self.game, 7, 0)
        self.assertEqual(self.game.combo, 1)

        for placement in range(2):
            place_1x1(self.game, placement, 5)
            self.assertEqual(self.game.combo, 1, "combo zginęło za wcześnie")

        place_1x1(self.game, 2, 5)
        self.assertEqual(self.game.combo, 0, "combo powinno zginąć przy trzecim postawieniu")

    def test_full_clear_bonus(self):
        # R-5: 300, nie 100.
        row_full_except(self.game, 7)
        gained = place_1x1(self.game, 7, 0)
        # 1 komórka + combo 1 x B(1) + pusta plansza
        self.assertEqual(gained, 1 + 10 + FULL_CLEAR_BONUS)


class TestScoreAccumulates(unittest.TestCase):
    """Warunek wstępny #8 nr 1: bez tego benchmark nie ma czego czytać."""

    def test_score_is_cumulative(self):
        game = Game(seed=7)
        running = 0
        for _ in range(10):
            actions = game.available_actions()
            if not actions or game.done:
                break
            gained, score, _, _ = game.step(actions[0])
            running += gained
            self.assertEqual(score, running)
        self.assertGreater(game.score, 10)

    def test_placements_count_survival(self):
        game = Game(seed=7)
        moves = 0
        while not game.done:
            actions = game.available_actions()
            if not actions:
                break
            game.step(actions[0])
            moves += 1
        self.assertEqual(game.placements, moves)


class TestGenerator(unittest.TestCase):
    """Warunek wstępny #8 nr 2: R-9 — seed był ignorowany."""

    def test_same_seed_gives_same_pieces(self):
        a = [p.name for p in Generator(99).next_pieces()]
        b = [p.name for p in Generator(99).next_pieces()]
        self.assertEqual(a, b)

    def test_different_seeds_diverge(self):
        streams = set()
        for seed in range(20):
            gen = Generator(seed)
            streams.add(tuple(p.name for p in gen.next_pieces()))
        self.assertGreater(len(streams), 1)

    def test_whole_game_is_reproducible(self):
        def play(seed):
            game = Game(seed=seed)
            while not game.done:
                actions = game.available_actions()
                if not actions:
                    break
                game.step(actions[0])
            return game.score, game.placements

        self.assertEqual(play(2024), play(2024))


class TestPiecePool(unittest.TestCase):
    """R-6, R-7, R-8: pula i rozkład losowania."""

    def test_pool_has_41_poses(self):
        self.assertEqual(len(PIECE_POOL), EXPECTED_POSES)

    def test_no_duplicate_shapes(self):
        # R-7: "O" i "2x2" były tym samym klockiem, przez co 2x2 wypadał 2x częściej.
        shapes = [tuple(tuple(row) for row in p.shape) for p in PIECE_POOL]
        self.assertEqual(len(shapes), len(set(shapes)))

    def test_orientation_counts_match_reference(self):
        expected = {
            "1x1": 1, "beam2": 2, "beam3": 2, "beam4": 2, "beam5": 2,
            "square2": 1, "rect23": 2, "square3": 1, "corner3": 4,
            "L": 8, "corner5": 4, "diag2": 2, "diag3": 2, "S": 4, "T": 4,
        }
        actual = {
            name: len(PIECE_TYPES[i]) for i, (name, _) in enumerate(CANONICAL_TYPES)
        }
        self.assertEqual(actual, expected)

    def test_sampling_is_uniform_over_types_not_poses(self):
        # R-8: typ 3x3 (1 orientacja) musi wypadać ~8x częściej niż konkretna poza L.
        gen = Generator(1234)
        counts = {}
        for _ in range(20000):
            piece = gen._next_piece()
            counts[piece.name] = counts.get(piece.name, 0) + 1
        square3 = counts.get("square3", 0)
        l_pose = counts.get("L-0", 0)
        self.assertGreater(square3 / max(l_pose, 1), 5.0)


class TestBenchmarkPrerequisites(unittest.TestCase):
    """Warunek wstępny #8 nr 3: agent musi umieć grać deterministycznie."""

    def test_agent_accepts_epsilon_zero(self):
        from agent import Agent

        agent = Agent()
        game = Game(seed=5)
        state = agent.get_state(game)
        agent.get_action(state[:3], epsilon=0.0)
        self.assertEqual(agent.epsilon, 0.0)


class TestTraySearchPolicy(unittest.TestCase):
    def test_build_gives_reset_and_act(self):
        policy = policies.build(None)
        policy.reset(0)
        game = Game(seed=3)
        actions = game.available_actions()
        self.assertIn(policy.act(game, actions), actions)

    def test_plays_only_legal_moves(self):
        for seed in range(3):
            game = Game(seed=seed)
            policy = policies.build(None)
            policy.reset(seed)
            for _ in range(60):
                actions = game.available_actions()
                if not actions or game.done:
                    break
                move = policy.act(game, actions)
                self.assertIn(move, actions)
                _, _, _, reason = game.step(move)
                self.assertNotEqual(reason, "wrong_placement")

    def test_accepts_pieces_without_pool_index(self):
        board = Board()
        board.grid[7][0] = 1
        pieces = [Piece([[1, 1, 1]], "bridge", -1), None, Piece([[1], [1]], "bridge", -1)]
        actions = [(i, x, y) for i, p in enumerate(pieces) if p is not None
                   for y in range(8) for x in range(8) if board.can_place_piece(p, x, y)]
        game = SimpleNamespace(board=board, pieces=pieces, combo=0)
        self.assertIn(policies.build(None).act(game, actions), actions)

    def test_bit_line_clear_matches_board(self):
        rng = random.Random(7)
        for _ in range(200):
            board = Board()
            board.grid = [[int(rng.random() < 0.8) for _ in range(8)] for _ in range(8)]
            rows, cols = board.check_full_lines()
            bits, lines = policies._clear_lines(policies._grid_bits(board.grid))
            ref = board.copy()
            ref.clear_lines(rows, cols)
            self.assertEqual(lines, len(rows) + len(cols))
            self.assertEqual(bits, policies._grid_bits(ref.grid))

    def test_inner_transitions_match_definition(self):
        rng = random.Random(11)
        for _ in range(200):
            grid = [[int(rng.random() < 0.5) for _ in range(8)] for _ in range(8)]
            expected = 0
            for y in range(8):
                for x in range(8):
                    for nx, ny in ((x + 1, y), (x, y + 1)):
                        if nx < 8 and ny < 8 and grid[y][x] != grid[ny][nx]:
                            expected += 1
            self.assertEqual(policies._inner_transitions(policies._grid_bits(grid)), expected)

    def test_isolated_matches_definition(self):
        rng = random.Random(13)
        for _ in range(200):
            grid = [[int(rng.random() < 0.6) for _ in range(8)] for _ in range(8)]
            expected = 0
            for y in range(8):
                for x in range(8):
                    if grid[y][x]:
                        continue
                    sides = ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1))
                    if all(not (0 <= nx < 8 and 0 <= ny < 8) or grid[ny][nx] for nx, ny in sides):
                        expected += 1
            self.assertEqual(policies._isolated(policies._grid_bits(grid)), expected)

    def test_risk_bounds(self):
        self.assertEqual(policies._risk(0), 0.0)
        full_board = policies._CUBE_W + policies._LIN_W + len(policies.PIECE_TYPES) * policies._DEAD_W
        self.assertAlmostEqual(policies._risk(policies._FULL), full_board)


class TestTail(unittest.TestCase):
    def setUp(self):
        rows = [[1] * Board.WIDTH for _ in range(Board.HEIGHT)]
        for x, y in [(0, 0), (1, 0), (7, 0), (0, 5), (1, 3), (2, 1), (3, 2), (4, 4), (5, 6), (6, 7)]:
            rows[y][x] = 0
        self.bits = policies._grid_bits(rows)
        self.domino = Piece([[1, 1]], "domino", 0)
        self.square = Piece([[1, 1, 1], [1, 1, 1], [1, 1, 1]], "square", 0)

    def test_second_domino_has_no_room(self):
        slots = [policies._shape_placements(self.domino.shape)] * 2
        self.assertFalse(policies._completable(self.bits, slots))
        self.assertTrue(policies._completable(self.bits, slots[:1]))

    def test_tail_counts_mixed_dead_trays_only(self):
        mixed_dead = [self.domino] * 3
        self.assertAlmostEqual(policies._tail_share(self.bits, [mixed_dead, [self.domino]]), 0.5)
        self.assertEqual(policies._tail_share(self.bits, [[self.square] * 3]), 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
