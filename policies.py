"""
Polityki grające, których używa benchmark.

Wszystkie są deterministyczne przy zadanym seedzie partii — benchmark mierzy,
co polityka umie, a nie jak wypada w trakcie nauki (#8).
"""
import random

from board import Board
from generator import Generator
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
_EDGE_MASK = _COL_MASKS[0] | _COL_MASKS[-1] | _ROW_MASKS[0] | _ROW_MASKS[-1]
_NOT_LEFT_COL = _FULL ^ _COL_MASKS[0]
_NOT_RIGHT_COL = _FULL ^ _COL_MASKS[-1]
_NOT_TOP_ROW = _FULL ^ _ROW_MASKS[0]
_NOT_BOTTOM_ROW = _FULL ^ _ROW_MASKS[-1]
_LINE_W = 4.2
_OCC_W = 1.4
_ISO_W = 0.75
_INNER_W = 1.5
_EDGE_W = 2.0
_CUBE_W = 400.0
_LIN_W = 80.0
_DEAD_W = 12.3
_BEAM = 48
_FINALS = 20
_TAIL_DRAWS = 64
_TAIL_W = 400.0


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
_TYPE_PLACEMENTS = [[_POSE_PLACEMENTS[i] for i in pose_indices] for pose_indices in PIECE_TYPES]


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


def _inner_transitions(bits):
    return ((bits ^ (bits >> 1)) & _NOT_RIGHT_COL).bit_count() + ((bits ^ (bits >> _W)) & _NOT_BOTTOM_ROW).bit_count()


def _isolated(bits):
    blocked = (
        (((bits << 1) & _NOT_LEFT_COL) | _COL_MASKS[0])
        & (((bits >> 1) & _NOT_RIGHT_COL) | _COL_MASKS[-1])
        & (((bits << _W) & _NOT_TOP_ROW) | _ROW_MASKS[0])
        & (((bits >> _W) & _NOT_BOTTOM_ROW) | _ROW_MASKS[-1])
    )
    return (blocked & (_FULL ^ bits)).bit_count()


def _fits(bits, placements):
    return any((bits & mask) == 0 for _, _, mask in placements)


def _value(clears, bits):
    return (
        _LINE_W * clears
        - _OCC_W * bits.bit_count()
        - _ISO_W * _isolated(bits)
        - _INNER_W * _inner_transitions(bits)
        - _EDGE_W * ((_FULL ^ bits) & _EDGE_MASK).bit_count()
    )


def _risk(bits):
    # Zgon na granicy tacki: wszystkie trzy klocki nowej tacki bez miejsca, stąd sześcian.
    shares = [sum(_fits(bits, placements) for placements in poses) / len(poses) for poses in _TYPE_PLACEMENTS]
    alive = [share for share in shares if share > 0.0]
    mean_all = sum(shares) / len(shares)
    mean_alive = sum(alive) / len(alive) if alive else 0.0
    return _CUBE_W * (1.0 - mean_alive) ** 3 + _LIN_W * (1.0 - mean_all) + _DEAD_W * (len(shares) - len(alive))


_SHAPE_PLACEMENTS = {}


def _shape_placements(shape):
    key = tuple(tuple(row) for row in shape)
    places = _SHAPE_PLACEMENTS.get(key)
    if places is None:
        places = _SHAPE_PLACEMENTS[key] = _placements(shape)
    return places


def _completable(bits, slots):
    if not slots:
        return True
    for j, places in enumerate(slots):
        rest = slots[:j] + slots[j + 1:]
        for _, _, mask in places:
            if bits & mask:
                continue
            child, _ = _clear_lines(bits | mask)
            if _completable(child, rest):
                return True
    return False


def _tail_share(bits, trays):
    dead = 0
    for tray in trays:
        slots = [_shape_placements(piece.shape) for piece in tray]
        if any(_fits(bits, places) for places in slots) and not _completable(bits, slots):
            dead += 1
    return dead / len(trays)


class TraySearchPolicy:
    """Wiązka po klockach tacki; finaliści oceniani ryzykiem następnej tacki i ogonem martwych tacek."""

    name = "tray"

    def __init__(self):
        self.reset(0)

    def reset(self, game_seed):
        # Osobne ziarno: losowanie z generatora gry zmieniłoby prawdziwe tacki.
        self._tail = Generator(f"ogon:{game_seed}")

    def act(self, game, actions):
        slots = [(idx, _shape_placements(piece.shape)) for idx, piece in enumerate(game.pieces) if piece is not None]
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
            trays = [self._tail.next_pieces() for _ in range(_TAIL_DRAWS)]
            return max(finalists, key=lambda s: s[0] - _risk(s[1]) - _TAIL_W * _tail_share(s[1], trays))[2]
        if last:
            return max(last, key=lambda s: s[0])[4]
        return actions[0]


def build(weights):
    return TraySearchPolicy()
