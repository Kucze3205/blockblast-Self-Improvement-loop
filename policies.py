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
from pieces import PIECE_POOL, PIECE_TYPES
from scoring import FULL_CLEAR_BONUS, clear_points, placement_points

NTUPLE_FILE = "ntuple.json"
EVAL_BEAM = 4
RISK_SAMPLES = 16
RISK_TOP = 8
POOL_KEYS = [valuation.shape_key(piece.shape) for piece in PIECE_POOL]


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

    def __init__(self, table, beam=1):
        self.table = table
        self.beam = beam

    def reset(self, game_seed):
        pass

    def act(self, game, actions):
        occ = valuation.occupancy(game.board.grid)
        afters = [_after(game, occ, action) for action in actions]
        values = [valuation.value(self.table, after) for after in afters]
        order = sorted(range(len(actions)), key=lambda i: -values[i])
        kept = []
        for i in order:
            if not _tray_survives(game, actions[i][0], afters[i]):
                continue
            if self.beam == 1:
                return actions[i]
            kept.append(i)
            if len(kept) == self.beam:
                break
        if not kept:
            return actions[order[0]]
        best = max(kept, key=lambda i: self._future(game, actions[i][0], afters[i]))
        return actions[best]

    def _future(self, game, idx, after):
        rest = [j for j, p in enumerate(game.pieces) if p is not None and j != idx]
        if not rest:
            return valuation.value(self.table, after)
        best = None
        for j in rest:
            others = tuple(
                valuation.shape_key(game.pieces[k].shape) for k in rest if k != j
            )
            mask, shifts = valuation.placements(valuation.shape_key(game.pieces[j].shape))
            for s in shifts:
                pm = mask << s
                if after & pm:
                    continue
                nxt = valuation.clear_full(after | pm)
                if others and not valuation.completable(nxt, others):
                    continue
                v = valuation.value(self.table, nxt)
                if best is None or v > best:
                    best = v
        return best

    def explore(self, game, actions, rng):
        occ = valuation.occupancy(game.board.grid)
        for action in rng.sample(actions, len(actions)):
            if _tray_survives(game, action[0], _after(game, occ, action)):
                return action
        return rng.choice(actions)


def _sample_tray(rng):
    return tuple(POOL_KEYS[rng.choice(rng.choice(PIECE_TYPES))] for _ in range(3))


def survival_fraction(after, trays):
    return sum(valuation.completable(after, tray) for tray in trays) / len(trays)


class RiskPolicy(NTuplePolicy):
    """Przy ostatnim klocku tacki: P(następna tacka da się położyć) razy wartość, na najlepszych kandydatach."""

    name = "risk"

    def __init__(self, table, beam=EVAL_BEAM, samples=RISK_SAMPLES, top=RISK_TOP):
        super().__init__(table, beam=beam)
        self.samples = samples
        self.top = top
        self.rng = random.Random(0)

    def reset(self, game_seed):
        self.rng = random.Random(f"risk:{game_seed}")

    def act(self, game, actions):
        if sum(1 for piece in game.pieces if piece is not None) != 1:
            return super().act(game, actions)
        occ = valuation.occupancy(game.board.grid)
        afters = [_after(game, occ, action) for action in actions]
        values = [valuation.value(self.table, after) for after in afters]
        order = sorted(range(len(actions)), key=lambda i: -values[i])[: self.top]
        trays = [_sample_tray(self.rng) for _ in range(self.samples)]
        best, best_score = order[0], None
        for i in order:
            score = survival_fraction(afters[i], trays) * max(values[i], 0.0)
            if best_score is None or score > best_score:
                best, best_score = i, score
        return actions[best]


def build(weights):
    if weights is None:
        return GreedyPolicy()
    path = os.path.join(weights, NTUPLE_FILE)
    if not os.path.exists(path):
        return GreedyPolicy()
    with open(path, encoding="utf-8") as fh:
        return RiskPolicy(valuation.load_table(json.load(fh)), beam=EVAL_BEAM)
