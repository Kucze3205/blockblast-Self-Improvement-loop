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


_W, _H = Board.WIDTH, Board.HEIGHT
_FULL = (1 << (_W * _H)) - 1
_ROW_MASKS = [((1 << _W) - 1) << (_W * y) for y in range(_H)]
_COL_MASKS = [sum(1 << (_W * y + x) for y in range(_H)) for x in range(_W)]
_LINE_MASKS = _ROW_MASKS + _COL_MASKS
_WALL_MASKS = (_COL_MASKS[0], _COL_MASKS[-1], _ROW_MASKS[0], _ROW_MASKS[-1])
_NOT_RIGHT_COL = sum(1 << (_W * y + x) for y in range(_H) for x in range(_W - 1))
_NOT_BOTTOM_ROW = (1 << (_W * (_H - 1))) - 1
_TRANS_W = 1.0
_LINE_W = 4.0
_TRAY_FAIL_W = 120.0
_BEAM = 12
_FINALS = 12


def _placements(shape):
    cells = [(dx, dy) for dy, row in enumerate(shape) for dx, cell in enumerate(row) if cell]
    h, w = len(shape), len(shape[0])
    out = []
    for y in range(_H - h + 1):
        for x in range(_W - w + 1):
            mask = 0
            for dx, dy in cells:
                mask |= 1 << (_W * (y + dy) + x + dx)
            out.append((x, y, mask))
    return out


_POSE_PLACEMENTS = [_placements(piece.shape) for piece in PIECE_POOL]
_POSE_PROB = [1.0 / (len(PIECE_TYPES) * len(PIECE_TYPES[piece.type_index])) for piece in PIECE_POOL]


def _grid_bits(grid):
    bits = 0
    for y, row in enumerate(grid):
        for x, cell in enumerate(row):
            if cell:
                bits |= 1 << (_W * y + x)
    return bits


def _clear_lines(bits):
    cleared = 0
    lines = 0
    for mask in _LINE_MASKS:
        if (bits & mask) == mask:
            cleared |= mask
            lines += 1
    return bits & ~cleared, lines


def _transitions(bits):
    empty = _FULL ^ bits
    inner = ((bits ^ (bits >> 1)) & _NOT_RIGHT_COL).bit_count()
    inner += ((bits ^ (bits >> _W)) & _NOT_BOTTOM_ROW).bit_count()
    walls = sum((empty & mask).bit_count() for mask in _WALL_MASKS)
    return inner + walls


def _nofit_probability(bits):
    total = 0.0
    for pose, placements in enumerate(_POSE_PLACEMENTS):
        if not any((bits & mask) == 0 for _, _, mask in placements):
            total += _POSE_PROB[pose]
    return total


def _fits(bits, placements):
    return any((bits & mask) == 0 for _, _, mask in placements)


def _value(clears, bits):
    return _LINE_W * clears - _TRANS_W * _transitions(bits)


def _risk(bits):
    # Gra kończy się, gdy zostaje klocek, który się nie mieści: liczy się P(choć jeden), nie P(wszystkie).
    p = _nofit_probability(bits)
    return _TRAY_FAIL_W * (1.0 - (1.0 - p) ** 3)


class TraySearchPolicy:
    """Wiązka po klockach tacki; finaliści oceniani ryzykiem następnej tacki."""

    name = "tray"

    def reset(self, game_seed):
        pass

    def act(self, game, actions):
        slots = [(idx, _placements(piece.shape)) for idx, piece in enumerate(game.pieces) if piece is not None]
        start = _grid_bits(game.board.grid)
        full_rem = (1 << len(slots)) - 1
        frontier = [(_value(0, start), 0, start, full_rem, None)]
        last = []
        complete = []
        while frontier:
            children = {}
            for _, clears, bits, rem, first in frontier:
                for j, (idx, places) in enumerate(slots):
                    if not (rem >> j) & 1:
                        continue
                    left = rem & ~(1 << j)
                    for x, y, mask in places:
                        if bits & mask:
                            continue
                        nxt, lines = _clear_lines(bits | mask)
                        cl = clears + lines
                        val = _value(cl, nxt)
                        key = (nxt, left)
                        prev = children.get(key)
                        if prev is None or val > prev[0]:
                            children[key] = (val, cl, nxt, left, first or (idx, x, y))
            frontier = []
            for val, cl, nxt, left, move in sorted(children.values(), key=lambda s: s[0], reverse=True):
                if left == 0:
                    complete.append((val, nxt, move))
                elif len(frontier) < _BEAM and any(
                    _fits(nxt, slots[k][1]) for k in range(len(slots)) if (left >> k) & 1
                ):
                    frontier.append((val, cl, nxt, left, move))
            if frontier:
                last = frontier
        if complete:
            finalists = sorted(complete, key=lambda s: s[0], reverse=True)[:_FINALS]
            return max(finalists, key=lambda s: s[0] - _risk(s[1]))[2]
        if last:
            return max(last, key=lambda s: s[0])[4]
        return actions[0]


def build(weights):
    return TraySearchPolicy()
