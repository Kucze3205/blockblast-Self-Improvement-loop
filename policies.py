"""
Polityki grające, których używa benchmark.

Wszystkie są deterministyczne przy zadanym seedzie partii — benchmark mierzy,
co polityka umie, a nie jak wypada w trakcie nauki (#8).
"""
import json
import os
import random

from board import Board
from scoring import FULL_CLEAR_BONUS, clear_points, placement_points
from search import FEATURE_COUNT, best_move, features, occupancy


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


DEFAULT_WEIGHTS = [-3.0, -2.0, -1.0, -1.0, -0.8, -0.8, 1.0, 1.0, -2.0, 0.5, 0.8, 0.0]
DEFAULT_BIAS = 0.0
SEARCH_WIDTH = 12


class SearchPolicy:
    """Wiązka po klockach tacki na bitboardach, ocena planszy liniowa z wag."""

    name = "search"

    def __init__(self, weights, bias, width):
        self._weights = list(weights)
        self._bias = bias
        self._width = width

    def reset(self, game_seed):
        pass

    def act(self, game, actions):
        occ = occupancy(game.board.grid)
        pieces = [(i, p.index) for i, p in enumerate(game.pieces) if p is not None]
        move = best_move(occ, pieces, self._value, self._width)
        return move if move is not None else actions[0]

    def _value(self, occ):
        return self._bias + sum(w * f for w, f in zip(self._weights, features(occ)))


def build(weights):
    if weights is None:
        return SearchPolicy(DEFAULT_WEIGHTS, DEFAULT_BIAS, SEARCH_WIDTH)
    with open(os.path.join(weights, "value.json")) as f:
        data = json.load(f)
    values = data["w"]
    assert len(values) == FEATURE_COUNT, f"wagi maja {len(values)} cech, oczekiwano {FEATURE_COUNT}"
    return SearchPolicy(values, float(data["b"]), SEARCH_WIDTH)
