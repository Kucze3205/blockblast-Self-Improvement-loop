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
_ROOT_WIDTH = 8
_MID_WIDTH = 3
_REVIEW = 4
_DRAWS = 16
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


def _order(after, lines, rest):
    empty = _FULL & ~after
    fits = sum(1 for _, shifts, valid in rest if _anchors(empty, shifts, valid))
    return (fits, lines, -_isolated(empty))


def _gain(cells, lines, after, base_combo):
    gain = cells
    if lines:
        gain += clear_points(base_combo + 1, lines)
    if after == 0:
        gain += FULL_CLEAR_BONUS
    return gain


_POSE_DESC = [_describe(p.shape) for p in PIECE_POOL]

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
        return _leaf(board, pts), board
    cands = []
    for k, (mask, shifts, valid) in enumerate(pending):
        anchors = _anchors(_FULL & ~board, shifts, valid)
        while anchors:
            low = anchors & -anchors
            anchors ^= low
            piece_bits = mask << (low.bit_length() - 1)
            after, lines = _clear(board | piece_bits)
            cands.append((k, after, lines, len(shifts)))
    best, leaf = _DEAD, None
    if len(pending) == 1:
        for _, after, lines, cells in cands:
            key = _leaf(after, pts + _gain(cells, lines, after, base_combo))
            if key > best:
                best, leaf = key, after
        return best, leaf
    ranked = []
    for k, after, lines, cells in cands:
        rest = pending[:k] + pending[k + 1:]
        ranked.append((_order(after, lines, rest), rest, after, lines, cells))
    ranked.sort(key=lambda c: c[0], reverse=True)
    for _, rest, after, lines, cells in ranked[:_MID_WIDTH]:
        key, sub = _search(after, rest, pts + _gain(cells, lines, after, base_combo), base_combo)
        if key > best:
            best, leaf = key, sub
    return best, leaf


def _completable(board, slots):
    if not slots:
        return True
    free = _FULL & ~board
    for i, (mask, shifts, valid) in enumerate(slots):
        anchors = _anchors(free, shifts, valid)
        rest = slots[:i] + slots[i + 1:]
        while anchors:
            low = anchors & -anchors
            anchors ^= low
            after, _ = _clear(board | (mask << (low.bit_length() - 1)))
            if _completable(after, rest):
                return True
    return False


class TrayPolicy:
    """Przeszukuje postawienia całej tacki; finalistów sprawdza CRN-owo: czy następna tacka się położy."""

    name = "tray-crn"

    def __init__(self):
        self.rng = random.Random(0)

    def reset(self, game_seed):
        self.rng = random.Random(game_seed)

    def act(self, game, actions):
        board = _bits(game.board.grid)
        base_combo = game.combo
        roots = []
        for action in actions:
            idx, x, y = action
            mask, _, _ = _describe(game.pieces[idx].shape)
            piece_bits = mask << (8 * y + x)
            after, lines = _clear(board | piece_bits)
            rest = [_describe(p.shape) for j, p in enumerate(game.pieces) if p is not None and j != idx]
            roots.append((_order(after, lines, rest), action, after, lines, mask.bit_count(), rest))
        roots.sort(key=lambda r: r[0], reverse=True)
        finals = []
        for _, action, after, lines, cells, rest in roots[:_ROOT_WIDTH]:
            key, leaf = _search(after, rest, _gain(cells, lines, after, base_combo), base_combo)
            finals.append((key, action, leaf))
        finals.sort(key=lambda f: f[0], reverse=True)
        draws = [
            [_POSE_DESC[self.rng.choice(self.rng.choice(PIECE_TYPES))] for _ in range(3)]
            for _ in range(_DRAWS)
        ]
        best_action, best_key = None, _DEAD
        for key, action, leaf in finals[:_REVIEW]:
            if leaf is None:
                review = key
            else:
                dead = sum(1 for draw in draws if not _completable(leaf, draw))
                review = (round(1.0 - dead / _DRAWS, 3),) + key[1:]
            if best_action is None or review > best_key:
                best_action, best_key = action, review
        return best_action


def build(weights=None):
    return TrayPolicy()
