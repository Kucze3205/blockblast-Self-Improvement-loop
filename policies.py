"""
Polityki grające, których używa benchmark.

Wszystkie są deterministyczne przy zadanym seedzie partii — benchmark mierzy,
co polityka umie, a nie jak wypada w trakcie nauki (#8).
"""
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


_FULL = (1 << 64) - 1
_ROW = [0xFF << (8 * r) for r in range(8)]
_COL = [sum(1 << (8 * r + c) for r in range(8)) for c in range(8)]
_NOT_C0 = _FULL ^ _COL[0]
_NOT_C7 = _FULL ^ _COL[7]
_INNER_H = _FULL ^ _COL[7]
_INNER_V = _FULL ^ _ROW[7]
_EDGE = _ROW[0] | _ROW[7] | _COL[0] | _COL[7]
_BEAM = 24
_FINALISTS = 16
_RISK_WEIGHT = 300.0


def _mask(pose, x, y):
    m = 0
    for dy, row in enumerate(PIECE_POOL[pose].shape):
        for dx, cell in enumerate(row):
            if cell:
                m |= 1 << ((y + dy) * 8 + x + dx)
    return m


def _positions(pose):
    shape = PIECE_POOL[pose].shape
    h, w = len(shape), len(shape[0])
    return [(x, y, _mask(pose, x, y)) for y in range(9 - h) for x in range(9 - w)]


_POSITIONS = [_positions(p) for p in range(len(PIECE_POOL))]


def _bits(grid):
    bits = 0
    for r, row in enumerate(grid):
        for c, cell in enumerate(row):
            if cell:
                bits |= 1 << (8 * r + c)
    return bits


def _place(bits, mask):
    filled = bits | mask
    clear = 0
    lines = 0
    for r in range(8):
        if (filled & _ROW[r]) == _ROW[r]:
            clear |= _ROW[r]
            lines += 1
    for c in range(8):
        if (filled & _COL[c]) == _COL[c]:
            clear |= _COL[c]
            lines += 1
    return filled & ~clear, lines


def _leaf(bits, lines):
    empty = _FULL ^ bits
    near = ((empty >> 1) & _NOT_C7) | ((empty << 1) & _NOT_C0) | (empty >> 8) | (empty << 8)
    isolated = empty & ~near
    trans = (bin((bits ^ (bits >> 1)) & _INNER_H).count("1")
             + bin((bits ^ (bits >> 8)) & _INNER_V).count("1"))
    return (-1.4 * bin(bits).count("1") - 0.75 * bin(isolated).count("1")
            - 1.5 * trans - 2.0 * bin(empty & _EDGE).count("1") + 4.2 * lines)


def _fits(bits, pose):
    return any((bits & m) == 0 for _, _, m in _POSITIONS[pose])


def _risk(bits):
    q = 0.0
    for poses in PIECE_TYPES:
        share = 1.0 / (len(PIECE_TYPES) * len(poses))
        q += share * sum(1 for p in poses if not _fits(bits, p))
    return 1.0 - (1.0 - q) ** 3


def _plan(bits, pending):
    frontier = [(bits, pending, None, 0)]
    finals = []
    while frontier:
        children = {}
        for b, rem, first, lines in frontier:
            for k, (slot, pose) in enumerate(rem):
                rest = rem[:k] + rem[k + 1:]
                for x, y, m in _POSITIONS[pose]:
                    if b & m:
                        continue
                    nb, cleared = _place(b, m)
                    move = first or (slot, x, y)
                    total = lines + cleared
                    if rest:
                        key = (nb, total, tuple(s for s, _ in rest))
                        children.setdefault(key, (nb, rest, move, total))
                    else:
                        finals.append((nb, move, total))
        ranked = sorted(children.values(), key=lambda s: -_leaf(s[0], s[3]))
        frontier = ranked[:_BEAM]
    if not finals:
        return None
    finals.sort(key=lambda f: -_leaf(f[0], f[2]))
    best, best_val = None, None
    for nb, move, total in finals[:_FINALISTS]:
        val = _leaf(nb, total) - _RISK_WEIGHT * _risk(nb)
        if best_val is None or val > best_val:
            best, best_val = move, val
    return best


def _single(bits, game, actions):
    best, best_val = None, None
    for idx, x, y in actions:
        nb, cleared = _place(bits, _mask(game.pieces[idx].index, x, y))
        val = _leaf(nb, cleared)
        if best_val is None or val > best_val:
            best, best_val = (idx, x, y), val
    return best


class SearchPolicy:
    name = "search"

    def reset(self, game_seed):
        pass

    def act(self, game, actions):
        bits = _bits(game.board.grid)
        pending = [(i, piece.index) for i, piece in enumerate(game.pieces) if piece is not None]
        move = _plan(bits, pending)
        return move if move is not None else _single(bits, game, actions)


def build(weights):
    return SearchPolicy()
