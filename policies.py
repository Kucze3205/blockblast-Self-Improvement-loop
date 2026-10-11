"""
Polityki grające, których używa benchmark.

Wszystkie są deterministyczne przy zadanym seedzie partii — benchmark mierzy,
co polityka umie, a nie jak wypada w trakcie nauki (#8).
"""
import json
import os
import random

import valuation
from board import Board
from scoring import FULL_CLEAR_BONUS, clear_points, placement_points

NTUPLE_FILE = "ntuple.json"


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


def _after(game, occ, action):
    idx, x, y = action
    return valuation.clear_full(occ | valuation.piece_mask(game.pieces[idx].shape, x, y))


def _tray_survives(game, idx, after):
    rest = tuple(
        valuation.shape_key(p.shape)
        for j, p in enumerate(game.pieces)
        if p is not None and j != idx
    )
    return valuation.completable(after, rest)


class NTuplePolicy:
    """Najwyższa wartość po postawieniu, pod warunkiem że tacka wciąż ma co położyć."""

    name = "ntuple"

    def __init__(self, table):
        self.table = table

    def reset(self, game_seed):
        pass

    def act(self, game, actions):
        occ = valuation.occupancy(game.board.grid)
        afters = [_after(game, occ, action) for action in actions]
        values = [valuation.value(self.table, after) for after in afters]
        order = sorted(range(len(actions)), key=lambda i: -values[i])
        for i in order:
            if _tray_survives(game, actions[i][0], afters[i]):
                return actions[i]
        return actions[order[0]]

    def explore(self, game, actions, rng):
        occ = valuation.occupancy(game.board.grid)
        for action in rng.sample(actions, len(actions)):
            if _tray_survives(game, action[0], _after(game, occ, action)):
                return action
        return rng.choice(actions)


def build(weights):
    if weights is None:
        return GreedyPolicy()
    path = os.path.join(weights, NTUPLE_FILE)
    if not os.path.exists(path):
        return GreedyPolicy()
    with open(path, encoding="utf-8") as fh:
        return NTuplePolicy(valuation.load_table(json.load(fh)))
