"""
Polityki grające, których używa benchmark.

Wszystkie są deterministyczne przy zadanym seedzie partii — benchmark mierzy,
co polityka umie, a nie jak wypada w trakcie nauki (#8).
"""
import random

from board import Board
from scoring import FULL_CLEAR_BONUS, clear_points, placement_points
from risk import dead_mass, death_probability, sample_trays
from tray_search import clear_count, from_grid, leaf, mask_at, popcount, shape_key, tray_finals

SAMPLES = 128
CANDIDATES = 8
LATE_CANDIDATES = 20
LATE_FREE = 22
TRAY_BEAM = 40


class RandomPolicy:
    """Jednostajnie po dostępnych ruchach. Dolna granica odniesienia."""

    name = "random"

    def __init__(self, seed=0):
        self._seed = seed

    def reset(self, game_seed):
        self.rng = random.Random(f"{self._seed}:{game_seed}")

    def act(self, game, actions):
        return self.rng.choice(actions)


class GreedyPolicy:
    """Maksymalizuje punkty z bieżącego postawienia (jeden pół-ruch w przód)."""

    name = "greedy"

    def reset(self, game_seed):
        pass

    def act(self, game, actions):
        best, best_gain = actions[0], None
        for action in actions:
            gain = _immediate_gain(game, action)
            if best_gain is None or gain > best_gain:
                best, best_gain = action, gain
        return best


class ModelPolicy:
    """Wytrenowana sieć w trybie deterministycznym (ε = 0)."""

    def __init__(self, agent, name):
        self.agent = agent
        self.name = name

    def reset(self, game_seed):
        pass

    def act(self, game, actions):
        grid, shapes, numeric, _ = self.agent.get_state(game)
        move = self.agent.get_action((grid, shapes, numeric), epsilon=0.0)
        return tuple(move)


def _immediate_gain(game, action):
    """Punkty, które da to postawienie — wg skalibrowanego wzoru, bez zmiany stanu gry."""
    idx, x, y = action
    piece = game.pieces[idx]
    board = game.board.copy()
    board.place_piece(piece, x, y)

    gain = placement_points(piece)
    rows, cols = board.check_full_lines()
    lines = len(rows) + len(cols)
    if lines > 0:
        gain += clear_points(game.combo + 1, lines)
        board.clear_lines(rows, cols)
        if not any(any(row) for row in board.grid):
            gain += FULL_CLEAR_BONUS
    return gain


def _step_value(board, key, action):
    _, x, y = action
    nb, cleared = clear_count(board | mask_at(key, x, y))
    return leaf(nb, cleared)


class TrayPolicy:
    """Ruch wiodący do tacki o najlepszym liściu kształtu minus ryzyko następnej tacki."""

    name = "tray"

    def __init__(self, trays, candidates, late_candidates, beam):
        self.trays = trays
        self.candidates = candidates
        self.late_candidates = late_candidates
        self.beam = beam

    def reset(self, game_seed):
        pass

    def act(self, game, actions):
        board = from_grid(game.board.grid)
        pieces = [(i, shape_key(p.shape)) for i, p in enumerate(game.pieces) if p is not None]
        finals = tray_finals(board, pieces, self.beam)
        if not finals:
            return max(actions, key=lambda a: _step_value(board, shape_key(game.pieces[a[0]].shape), a))
        limit = self.late_candidates if 64 - popcount(board) <= LATE_FREE else self.candidates
        best = max(finals[:limit], key=lambda f: f[0] - self._penalty(f[1]))
        return best[2]

    def _penalty(self, board):
        return 400 * death_probability(board, self.trays) + 80 * dead_mass(board)


def build(weights):
    return TrayPolicy(sample_trays(SAMPLES), CANDIDATES, LATE_CANDIDATES, TRAY_BEAM)
