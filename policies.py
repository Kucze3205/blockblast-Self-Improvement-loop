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


_N = 8
_FULL = (1 << (_N * _N)) - 1
_LEFT_COL = sum(1 << (_N * r) for r in range(_N))
_RIGHT_COL = _LEFT_COL << (_N - 1)
_NOT_LEFT = _FULL ^ _LEFT_COL
_NOT_RIGHT = _FULL ^ _RIGHT_COL
_ROW_MASKS = [((1 << _N) - 1) << (_N * r) for r in range(_N)]
_COL_MASKS = [sum(1 << (c + _N * r) for r in range(_N)) for c in range(_N)]


def _placements(piece):
    h, w = len(piece.shape), len(piece.shape[0])
    out = []
    for y in range(_N - h + 1):
        for x in range(_N - w + 1):
            mask = 0
            for dy, row in enumerate(piece.shape):
                for dx, cell in enumerate(row):
                    if cell:
                        mask |= 1 << ((y + dy) * _N + x + dx)
            out.append((x, y, mask))
    return out


_PLACEMENTS = [_placements(p) for p in PIECE_POOL]
_MASK_AT = [{(x, y): m for x, y, m in plc} for plc in _PLACEMENTS]


def _board_mask(grid):
    mask = 0
    for r, row in enumerate(grid):
        for c, cell in enumerate(row):
            if cell:
                mask |= 1 << (_N * r + c)
    return mask


def _place(board, piece_mask):
    filled = board | piece_mask
    clear, lines = 0, 0
    for m in _ROW_MASKS + _COL_MASKS:
        if (filled & m) == m:
            clear |= m
            lines += 1
    return filled & ~clear, lines


def _value(board, lines):
    empty = ~board & _FULL
    empty_nb = (
        ((empty & _NOT_LEFT) >> 1)
        | ((empty & _NOT_RIGHT) << 1)
        | (empty >> _N)
        | ((empty << _N) & _FULL)
    )
    isolated = (empty & ~empty_nb).bit_count()
    hpair = empty & ((empty & _NOT_LEFT) >> 1)
    squares = (hpair & (hpair >> _N)).bit_count()
    return 2.0 * lines - 3.0 * isolated + squares


_POSE_ANCHORS = [
    sum(1 << (_N * y + x) for y in range(_N - len(p.shape) + 1) for x in range(_N - len(p.shape[0]) + 1))
    for p in PIECE_POOL
]
_POSE_SHIFTS = [
    [_N * dy + dx for dy, row in enumerate(p.shape) for dx, cell in enumerate(row) if cell]
    for p in PIECE_POOL
]
_POSE_WEIGHT = [0.0] * len(PIECE_POOL)
for _members in PIECE_TYPES:
    for _pid in _members:
        _POSE_WEIGHT[_pid] = 1.0 / (len(PIECE_TYPES) * len(_members))

_TRAY_BEAM = (12, 6)


def _fit_probability(empty):
    """P(losowy klocek generatora mieści się na planszy): typ 1/15, potem poza 1/n."""
    q = 0.0
    for pid, anchors in enumerate(_POSE_ANCHORS):
        for shift in _POSE_SHIFTS[pid]:
            anchors &= empty >> shift
            if not anchors:
                break
        if anchors:
            q += _POSE_WEIGHT[pid]
    return q


def _tray_scores(board, tray):
    states = [(board, tray, None, 0)]
    for depth in range(len(tray)):
        children = []
        for b, rest, root, cleared in states:
            for k, (j, pid) in enumerate(rest):
                left = rest[:k] + rest[k + 1:]
                for x, y, pm in _PLACEMENTS[pid]:
                    if b & pm:
                        continue
                    nxt, lines = _place(b, pm)
                    children.append((_value(nxt, lines), nxt, left, root or (j, x, y), cleared + lines))
        if depth + 1 < len(tray):
            children.sort(key=lambda c: c[0], reverse=True)
            del children[_TRAY_BEAM[depth]:]
        states = [(nxt, left, root, cleared) for _, nxt, left, root, cleared in children]
    scores = {}
    for nxt, _, root, cleared in states:
        key = (1.0 - (1.0 - _fit_probability(~nxt & _FULL)) ** 3, _value(nxt, cleared))
        if root not in scores or key > scores[root]:
            scores[root] = key
    return scores


class TrayFitPolicy:
    """Wiązka po kolejnościach tacki; liść oceniany szansą, że następna tacka ma mieszczący się klocek."""

    name = "tray-fit"

    def reset(self, game_seed):
        pass

    def act(self, game, actions):
        board = _board_mask(game.board.grid)
        tray = tuple((j, p.index) for j, p in enumerate(game.pieces) if p is not None)
        scores = _tray_scores(board, tray)
        if scores:
            return max(scores, key=scores.get)
        return max(
            actions,
            key=lambda a: _value(*_place(board, _MASK_AT[game.pieces[a[0]].index][(a[1], a[2])])),
        )


def build(weights):
    return TrayFitPolicy()
