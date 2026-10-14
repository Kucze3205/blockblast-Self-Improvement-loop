"""
Polityki grające, których używa benchmark.

Wszystkie są deterministyczne przy zadanym seedzie partii — benchmark mierzy,
co polityka umie, a nie jak wypada w trakcie nauki (#8).
"""
import heapq
import random

from board import Board
from pieces import PIECE_POOL, PIECE_TYPES
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


W = 8
FULL = (1 << (W * W)) - 1
ROW_MASKS = [0xFF << (W * r) for r in range(W)]
COL_MASKS = [sum(1 << (W * r + c) for r in range(W)) for c in range(W)]


def _pose_bits(shape):
    cells = [dy * W + dx for dy, row in enumerate(shape) for dx, v in enumerate(row) if v]
    return sum(1 << c for c in cells), cells, _anchor_mask(len(shape), len(shape[0]))


def _anchor_mask(h, w):
    mask = 0
    for y in range(W - h + 1):
        for x in range(W - w + 1):
            mask |= 1 << (y * W + x)
    return mask


def _legal_anchors(board_bits, pose):
    acc = pose[2]
    empty = board_bits ^ FULL
    for shift in pose[1]:
        acc &= empty >> shift
        if not acc:
            return 0
    return acc


_POSES = [_pose_bits(p.shape) for p in PIECE_POOL]
_PROB_POSES = [(1.0 / (15 * len(PIECE_TYPES[p.type_index])), _POSES[i]) for i, p in enumerate(PIECE_POOL)]
INTERIOR = sum(1 << (W * y + x) for y in range(1, W - 1) for x in range(1, W - 1))
BOUNDARY = FULL ^ INTERIOR
NOT_RIGHT = sum(1 << (W * y + x) for y in range(W) for x in range(W - 1))
NOT_BOTTOM = FULL >> W
LAMBDA_DEATH = 1000.0
W_CLEAR = 10.0
W_CELLS = 1.0
W_EDGE = 2.0
W_TRANS = 0.5


def _shape_key(piece):
    return tuple(tuple(int(bool(v)) for v in row) for row in piece.shape)


_SHAPE_POSE = {_shape_key(p): i for i, p in enumerate(PIECE_POOL)}


def _occupancy(grid):
    occ = 0
    for y, row in enumerate(grid):
        for x, v in enumerate(row):
            if v:
                occ |= 1 << (W * y + x)
    return occ


def _clear(occ):
    kill = 0
    cleared = 0
    for mask in ROW_MASKS + COL_MASKS:
        if (occ & mask) == mask:
            kill |= mask
            cleared += 1
    return occ & ~kill, cleared


def _fit_probability(occ):
    q = 0.0
    for prob, pose in _PROB_POSES:
        if _legal_anchors(occ, pose):
            q += prob
    return q


def _transitions(occ):
    return bin((occ ^ (occ >> 1)) & NOT_RIGHT).count("1") + bin((occ ^ (occ >> W)) & NOT_BOTTOM).count("1")


def _cheap(occ, cleared):
    edge = bin(~occ & BOUNDARY).count("1")
    return (
        W_CLEAR * cleared
        - W_CELLS * bin(occ).count("1")
        - W_EDGE * edge
        - W_TRANS * _transitions(occ)
    )


def _leaf_value(occ, cleared):
    dead = (1.0 - _fit_probability(occ)) ** 3
    return _cheap(occ, cleared) - LAMBDA_DEATH * dead


def _plan(occ, tray, width):
    frontier = [(occ, tuple(tray), None, 0)]
    for _ in range(len(tray)):
        children = []
        for board, rem, first, cleared in frontier:
            for k, (gi, pid) in enumerate(rem):
                rest = rem[:k] + rem[k + 1:]
                pose = _POSES[pid]
                anchors = _legal_anchors(board, pose)
                while anchors:
                    low = anchors & -anchors
                    anchors ^= low
                    a = low.bit_length() - 1
                    nxt, lines = _clear(board | (pose[0] << a))
                    if rest and not any(_legal_anchors(nxt, _POSES[r[1]]) for r in rest):
                        continue
                    act = first or (gi, a % W, a // W)
                    children.append((nxt, rest, act, cleared + lines))
        if not children:
            return None
        frontier = heapq.nlargest(width, children, key=lambda c: _cheap(c[0], c[3]))
    return max(frontier, key=lambda c: _leaf_value(c[0], c[3]))[2]


class TrayPolicy:
    name = "tray"

    def __init__(self, width=40):
        self.width = width

    def reset(self, game_seed):
        pass

    def act(self, game, actions):
        tray = [(i, _SHAPE_POSE[_shape_key(p)]) for i, p in enumerate(game.pieces) if p is not None]
        move = _plan(_occupancy(game.board.grid), tray, self.width)
        return move if move is not None else actions[0]


def build(weights):
    return TrayPolicy()


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
