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
_NOT_COL0 = _FULL & ~_COL[0]
_NOT_COL7 = _FULL & ~_COL[7]
_LINE_W, _FILLED_W, _ISO_W, _HOLE_W, _AGG_W, _DEAD_W, _RISK_W, _MOB_W = 4.2, 1.4, 0.75, 2.0, 0.6, 12.3, 400.0, 1.0
_BEAM, _FINAL_BEAM = 8, 16


def _pose_table():
    table = []
    for pose in PIECE_POOL:
        shape = pose.shape
        h, w = len(shape), len(shape[0])
        cells = [(r, c) for r, row in enumerate(shape) for c, cell in enumerate(row) if cell]
        shape_bits = sum(1 << (r * 8 + c) for r, c in cells)
        shifts = [r * 8 + c for r, c in cells]
        anchors = sum(1 << (y * 8 + x) for y in range(9 - h) for x in range(9 - w))
        table.append((shape_bits, shifts, anchors))
    return table


_POSES = _pose_table()
_POSE_WEIGHT = [0.0] * len(PIECE_POOL)
for _poses in PIECE_TYPES:
    for _p in _poses:
        _POSE_WEIGHT[_p] = 1.0 / (len(PIECE_TYPES) * len(_poses))


def _fits(free, p):
    """Maska kotwic, w których poza p mieści się w wolnych polach."""
    _, shifts, fits = _POSES[p]
    for s in shifts:
        fits &= free >> s
        if not fits:
            return 0
    return fits


def _clear(board):
    mask = 0
    cleared = 0
    for row in _ROW:
        if (board & row) == row:
            mask |= row
            cleared += 1
    for col in _COL:
        if (board & col) == col:
            mask |= col
            cleared += 1
    return board & ~mask, cleared


def _cheap(board, lines):
    free = _FULL & ~board
    near = (((free >> 1) & _NOT_COL7) | ((free << 1) & _NOT_COL0) | (free >> 8) | (free << 8)) & _FULL
    isolated = (free & ~near).bit_count()
    shadow = board | ((board << 8) & _FULL)
    shadow |= (shadow << 16) & _FULL
    shadow |= (shadow << 32) & _FULL
    holes = (shadow & free).bit_count()
    height = shadow.bit_count()
    return (_LINE_W * lines - _FILLED_W * board.bit_count() - _ISO_W * isolated
            - _HOLE_W * holes - _AGG_W * height)


def _tray_risk(board):
    free = _FULL & ~board
    q = 0.0
    dead = 0
    mobility = 0.0
    for poses in PIECE_TYPES:
        type_dead = True
        for p in poses:
            fits = _fits(free, p)
            if fits:
                type_dead = False
                mobility += _POSE_WEIGHT[p] * fits.bit_count()
            else:
                q += _POSE_WEIGHT[p]
        dead += type_dead
    return q, dead, mobility


def _choose(game, actions):
    root = 0
    for y, row in enumerate(game.board.grid):
        for x, cell in enumerate(row):
            if cell:
                root |= 1 << (y * 8 + x)
    left = tuple((i, p.index) for i, p in enumerate(game.pieces) if p is not None)
    beam = [(0.0, root, 0, left, None)]
    fallback = None
    while beam[0][3]:
        children = []
        for _, board, lines, rest_all, first in beam:
            for k, (slot, p) in enumerate(rest_all):
                rest = rest_all[:k] + rest_all[k + 1:]
                fits = _fits(_FULL & ~board, p)
                while fits:
                    low = fits & -fits
                    fits ^= low
                    anchor = low.bit_length() - 1
                    nxt, cleared = _clear(board | (_POSES[p][0] << anchor))
                    if rest and not any(_fits(_FULL & ~nxt, q) for _, q in rest):
                        continue
                    total = lines + cleared
                    action = first or (slot, anchor & 7, anchor >> 3)
                    children.append((_cheap(nxt, total), nxt, total, rest, action))
        if not children:
            break
        children.sort(key=lambda child: child[0], reverse=True)
        if fallback is None:
            fallback = children[0][4]
        keep = _FINAL_BEAM if not children[0][3] else _BEAM
        beam = children[:keep]

    if not beam[0][3] and beam[0][4] is not None:
        best = None
        for cheap, board, _, _, action in beam:
            q, dead, mobility = _tray_risk(board)
            value = cheap - _DEAD_W * dead - _RISK_W * q ** 3 + _MOB_W * mobility
            if best is None or value > best[0]:
                best = (value, action)
        return best[1]
    return fallback if fallback is not None else actions[0]


class TrayBeamPolicy:
    name = "tray-beam"

    def reset(self, game_seed):
        pass

    def act(self, game, actions):
        return _choose(game, actions)


def build(weights=None):
    return TrayBeamPolicy()
