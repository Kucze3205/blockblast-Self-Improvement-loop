"""
Polityki grające, których używa benchmark.

Wszystkie są deterministyczne przy zadanym seedzie partii — benchmark mierzy,
co polityka umie, a nie jak wypada w trakcie nauki (#8).
"""
import random

from board import Board
from scoring import FULL_CLEAR_BONUS, clear_points, placement_points


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


class SurvivalPolicy:
    """Wybiera ruch, który zostawia najwięcej legalnych postawień dla reszty tacki."""

    name = "survival"

    def reset(self, game_seed):
        pass

    def act(self, game, actions):
        best, best_key = actions[0], None
        for action in actions:
            key = _survival_key(game, action)
            if best_key is None or key > best_key:
                best, best_key = action, key
        return best


def build(weights=None):
    return SurvivalPolicy()


def _survival_key(game, action):
    idx, x, y = action
    piece = game.pieces[idx]
    board = game.board.copy()
    board.place_piece(piece, x, y)

    rows, cols = board.check_full_lines()
    lines = len(rows) + len(cols)
    board.clear_lines(rows, cols)

    remaining = [p for i, p in enumerate(game.pieces) if p is not None and i != idx]
    mobility = 0
    for other in remaining:
        for y2 in range(8 - len(other.shape) + 1):
            for x2 in range(8 - len(other.shape[0]) + 1):
                if board.can_place_piece(other, x2, y2):
                    mobility += 1

    filled = sum(sum(row) for row in board.grid)
    return (mobility, lines, -filled)


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
