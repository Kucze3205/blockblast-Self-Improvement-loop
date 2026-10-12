"""
Polityki grające, których używa benchmark.

Wszystkie są deterministyczne przy zadanym seedzie partii — benchmark mierzy,
co polityka umie, a nie jak wypada w trakcie nauki (#8).
"""
import random

from board import Board
from scoring import FULL_CLEAR_BONUS, clear_points, placement_points
from pieces import PIECE_POOL, PIECE_TYPES


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
_ROW_MASKS = [0xFF << (8 * y) for y in range(8)]
_COL_MASKS = [sum(1 << (8 * y + x) for y in range(8)) for x in range(8)]
_LINE_MASKS = _ROW_MASKS + _COL_MASKS
_NOT_COL0 = _FULL & ~_COL_MASKS[0]
_NOT_COL7 = _FULL & ~_COL_MASKS[7]
_BORDER = _ROW_MASKS[0] | _ROW_MASKS[7] | _COL_MASKS[0] | _COL_MASKS[7]
_ROOT_WIDTH = 8
_DEAD = (-1.0, 0.0, 0, 0)
_DESC_CACHE = {}


def _bits(grid):
    bits = 0
    for y, row in enumerate(grid):
        for x, cell in enumerate(row):
            if cell:
                bits |= 1 << (8 * y + x)
    return bits


def _describe(shape):
    key = tuple(tuple(row) for row in shape)
    desc = _DESC_CACHE.get(key)
    if desc is None:
        cells = [(r, c) for r, row in enumerate(shape) for c, cell in enumerate(row) if cell]
        shifts = tuple(8 * r + c for r, c in cells)
        mask = sum(1 << s for s in shifts)
        max_r = max(r for r, _ in cells)
        max_c = max(c for _, c in cells)
        valid = sum(1 << (8 * y + x) for y in range(8 - max_r) for x in range(8 - max_c))
        desc = (mask, shifts, valid)
        _DESC_CACHE[key] = desc
    return desc


def _anchors(empty, shifts, valid):
    anchors = valid
    for s in shifts:
        anchors &= empty >> s
        if not anchors:
            break
    return anchors


def _clear(board):
    gone, lines = 0, 0
    for mask in _LINE_MASKS:
        if (board & mask) == mask:
            gone |= mask
            lines += 1
    return board & ~gone, lines


def _isolated(empty):
    touched = ((empty >> 1) & _NOT_COL7) | ((empty << 1) & _NOT_COL0) | (empty << 8) | (empty >> 8)
    return (empty & ~touched).bit_count()


def _quick(board, piece_bits, after, lines):
    touch = ((piece_bits << 1) & _NOT_COL0) | ((piece_bits >> 1) & _NOT_COL7) | (piece_bits << 8) | (piece_bits >> 8)
    contact = (touch & board).bit_count() + (piece_bits & _BORDER).bit_count()
    return (4 * lines - _isolated(_FULL & ~after), contact)


def _gain(cells, lines, after, base_combo):
    gain = cells
    if lines:
        gain += clear_points(base_combo + 1, lines)
    if after == 0:
        gain += FULL_CLEAR_BONUS
    return gain


_LEAF_POSES = [
    (_describe(PIECE_POOL[pose].shape), 1.0 / (len(PIECE_TYPES) * len(poses)))
    for poses in PIECE_TYPES
    for pose in poses
]


def _leaf(board, pts):
    empty = _FULL & ~board
    fits, mobility = 0.0, 0.0
    for (_, shifts, valid), prob in _LEAF_POSES:
        anchors = _anchors(empty, shifts, valid)
        if anchors:
            fits += prob
            mobility += prob * anchors.bit_count()
    death = (1.0 - fits) ** 3
    return (round(1.0 - death, 3), mobility, -_isolated(empty), pts)


def _search(board, pending, pts, base_combo):
    if not pending:
        return _leaf(board, pts)
    width = 3 if len(pending) > 1 else 2
    cands = []
    for k, (mask, shifts, valid) in enumerate(pending):
        anchors = _anchors(_FULL & ~board, shifts, valid)
        while anchors:
            low = anchors & -anchors
            anchors ^= low
            piece_bits = mask << (low.bit_length() - 1)
            after, lines = _clear(board | piece_bits)
            cands.append((_quick(board, piece_bits, after, lines), k, after, lines, len(shifts)))
    cands.sort(key=lambda c: c[0], reverse=True)
    best = _DEAD
    for _, k, after, lines, cells in cands[:width]:
        rest = pending[:k] + pending[k + 1:]
        key = _search(after, rest, pts + _gain(cells, lines, after, base_combo), base_combo)
        if key > best:
            best = key
    return best


class TrayPolicy:
    """Przeszukuje postawienia całej tacki; plansza po niej oceniana szansą na start następnej."""

    name = "tray"

    def reset(self, game_seed):
        pass

    def act(self, game, actions):
        board = _bits(game.board.grid)
        base_combo = game.combo
        roots = []
        for action in actions:
            idx, x, y = action
            mask, _, _ = _describe(game.pieces[idx].shape)
            piece_bits = mask << (8 * y + x)
            after, lines = _clear(board | piece_bits)
            roots.append((_quick(board, piece_bits, after, lines), action, after, lines, mask.bit_count()))
        roots.sort(key=lambda r: r[0], reverse=True)
        best_action, best_key = None, _DEAD
        for _, action, after, lines, cells in roots[:_ROOT_WIDTH]:
            idx = action[0]
            rest = [_describe(p.shape) for j, p in enumerate(game.pieces) if p is not None and j != idx]
            key = _search(after, rest, _gain(cells, lines, after, base_combo), base_combo)
            if best_action is None or key > best_key:
                best_action, best_key = action, key
        return best_action


def build(weights=None):
    return TrayPolicy()
