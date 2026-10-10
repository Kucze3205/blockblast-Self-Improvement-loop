"""
Polityki grające, których używa benchmark.

Wszystkie są deterministyczne przy zadanym seedzie partii — benchmark mierzy,
co polityka umie, a nie jak wypada w trakcie nauki (#8).
"""
import json
import os
import random
from itertools import combinations_with_replacement, permutations

from board import Board
from pieces import PIECE_POOL, PIECE_TYPES
from scoring import FULL_CLEAR_BONUS, clear_points, placement_points

FULL = (1 << 64) - 1
ROWS = [0xFF << (8 * r) for r in range(8)]
COLS = [0x0101010101010101 << c for c in range(8)]
NOT_COL0 = FULL & ~COLS[0]
NOT_COL7 = FULL & ~COLS[7]
NOT_ROW7 = FULL & ~ROWS[7]
RING = ROWS[0] | ROWS[7] | COLS[0] | COLS[7]
BEAM = 12
FINAL = 12
HARD_TYPES = (3, 4, 6, 7, 10)
HARD_DRAWS = 3
DEFAULT_PARAMS = {
    "lines": 4.2, "occ": 1.4, "iso": 0.75, "trans": 1.5, "edge": 2.0,
    "fit_cube": 400.0, "fit_mean": 80.0, "dead": 12.3, "hard": 400.0,
}

_MASKS = {}
HARD_MULTISETS = [
    (c, len(set(permutations(c))) / 125)
    for c in combinations_with_replacement(HARD_TYPES, 3)
]


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


class BeamPolicy:
    """Beam po tacce na bitboardach: plan dla całej tacki, potem wykonywany krok po kroku."""

    name = "beam"

    def __init__(self, params):
        self.params = params
        self._plan = []

    def reset(self, game_seed):
        self._plan = []
        self.rng = random.Random(game_seed)

    def act(self, game, actions):
        legal = set(actions)
        if self._plan and self._plan[0] in legal:
            return self._plan.pop(0)
        self._plan = self._plan_tray(_bits(game.board.grid), game.pieces)
        if self._plan and self._plan[0] in legal:
            return self._plan.pop(0)
        return actions[0]

    def _plan_tray(self, bits, pieces):
        draws = self._draw_hard_poses()
        beam = [(bits, tuple(i for i, p in enumerate(pieces) if p is not None), (), 0)]
        best = ()
        while True:
            nxt = []
            for board, rem, acts, cleared in beam:
                for idx in rem:
                    mask, h, w = _shape_mask(pieces[idx].shape)
                    left = tuple(j for j in rem if j != idx)
                    for y in range(Board.HEIGHT - h + 1):
                        for x in range(Board.WIDTH - w + 1):
                            m = mask << (y * 8 + x)
                            if board & m:
                                continue
                            after, lines = _clear(board | m)
                            total = cleared + lines
                            nxt.append((self._leaf(after, total), after, left, total, acts + ((idx, x, y),)))
            if not nxt:
                break
            nxt.sort(key=lambda t: t[0], reverse=True)
            if not nxt[0][2]:
                finals = nxt[:FINAL]
                _, _, _, _, acts = max(
                    finals,
                    key=lambda t: t[0] - self._fit_penalty(t[1]) - self.params["hard"] * self._risk(t[1], draws),
                )
                return list(acts)
            beam = [(b, r, a, c) for _, b, r, c, a in nxt[:BEAM]]
            best = beam[0][2]
        return list(best)

    def _draw_hard_poses(self):
        return {
            t: [_shape_mask(PIECE_POOL[self.rng.choice(PIECE_TYPES[t])].shape) for _ in range(HARD_DRAWS)]
            for t in HARD_TYPES
        }

    def _risk(self, bits, draws):
        risk = 0.0
        for types, weight in HARD_MULTISETS:
            used = {}
            trio = []
            for t in types:
                k = used.get(t, 0)
                used[t] = k + 1
                trio.append(draws[t][k])
            if not _fits(bits, trio):
                risk += weight
        return risk

    def _leaf(self, bits, lines):
        p = self.params
        occ, iso, trans, edge = _features(bits)
        return p["lines"] * lines - p["occ"] * occ - p["iso"] * iso - p["trans"] * trans - p["edge"] * edge

    def _fit_penalty(self, bits):
        p = self.params
        shares = []
        dead = 0
        for poses in PIECE_TYPES:
            fitting = sum(1 for pose in poses if any(not (bits & m) for m in POSE_MASKS[pose]))
            shares.append(fitting / len(poses))
            if fitting == 0:
                dead += 1
        mean_all = sum(shares) / len(shares)
        alive = [share for share in shares if share > 0]
        mean_alive = sum(alive) / len(alive) if alive else 0.0
        return p["fit_cube"] * (1 - mean_alive) ** 3 + p["fit_mean"] * (1 - mean_all) + p["dead"] * dead


def build(weights=None):
    params = dict(DEFAULT_PARAMS)
    if weights is not None:
        path = os.path.join(weights, "params.json")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                params.update(json.load(fh))
    return BeamPolicy(params)


def _bits(grid):
    bits = 0
    for y, row in enumerate(grid):
        for x, cell in enumerate(row):
            if cell:
                bits |= 1 << (y * 8 + x)
    return bits


def _fits(bits, pieces):
    if not pieces:
        return True
    for i, (mask, h, w) in enumerate(pieces):
        rest = pieces[:i] + pieces[i + 1:]
        for y in range(Board.HEIGHT - h + 1):
            for x in range(Board.WIDTH - w + 1):
                m = mask << (y * 8 + x)
                if not (bits & m) and _fits(_clear(bits | m)[0], rest):
                    return True
    return False


def _shape_mask(shape):
    key = tuple(tuple(row) for row in shape)
    if key not in _MASKS:
        bits = 0
        for dy, row in enumerate(shape):
            for dx, cell in enumerate(row):
                if cell:
                    bits |= 1 << (dy * 8 + dx)
        _MASKS[key] = (bits, len(shape), len(shape[0]))
    return _MASKS[key]


def _features(bits):
    left = (bits << 1) & NOT_COL0
    right = (bits >> 1) & NOT_COL7
    up = (bits << 8) & FULL
    down = bits >> 8
    pockets = (left & right & up) | (left & right & down) | (left & up & down) | (right & up & down)
    trans = ((bits ^ (bits >> 1)) & NOT_COL7).bit_count() + ((bits ^ (bits >> 8)) & NOT_ROW7).bit_count()
    return bits.bit_count(), (pockets & ~bits).bit_count(), trans, (RING & ~bits).bit_count()


POSE_MASKS = [
    [mask << (y * 8 + x) for y in range(Board.HEIGHT - h + 1) for x in range(Board.WIDTH - w + 1)]
    for mask, h, w in (_shape_mask(piece.shape) for piece in PIECE_POOL)
]


def _clear(bits):
    full_rows = [m for m in ROWS if (bits & m) == m]
    full_cols = [m for m in COLS if (bits & m) == m]
    for m in full_rows + full_cols:
        bits &= ~m
    return bits, len(full_rows) + len(full_cols)


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
