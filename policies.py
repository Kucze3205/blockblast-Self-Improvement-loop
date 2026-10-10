"""
Polityki grające, których używa benchmark.

Wszystkie są deterministyczne przy zadanym seedzie partii — benchmark mierzy,
co polityka umie, a nie jak wypada w trakcie nauki (#8).
"""
import math
import random
from collections import Counter
from itertools import combinations_with_replacement

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


ROW_MASKS = [0xFF << (8 * y) for y in range(8)]
COL_MASKS = [sum(1 << (8 * y + x) for y in range(8)) for x in range(8)]
FULL = (1 << 64) - 1
NOT_COL0 = FULL & ~COL_MASKS[0]
NOT_COL7 = FULL & ~COL_MASKS[7]
BORDER = ROW_MASKS[0] | ROW_MASKS[7] | COL_MASKS[0] | COL_MASKS[7]
_placements = {}


def _piece_placements(piece):
    cached = _placements.get(piece.index)
    if cached is None:
        cells = [(dy, dx) for dy, row in enumerate(piece.shape) for dx, cell in enumerate(row) if cell]
        height, width = len(piece.shape), len(piece.shape[0])
        cached = {
            (x, y): sum(1 << (8 * (y + dy) + x + dx) for dy, dx in cells)
            for y in range(8 - height + 1)
            for x in range(8 - width + 1)
        }
        _placements[piece.index] = cached
    return cached


def _bitboard(grid):
    bits = 0
    for y, row in enumerate(grid):
        for x, cell in enumerate(row):
            if cell:
                bits |= 1 << (8 * y + x)
    return bits


def _clear_lines(bits):
    cleared, lines = 0, 0
    for mask in ROW_MASKS + COL_MASKS:
        if (bits & mask) == mask:
            cleared |= mask
            lines += 1
    return bits & ~cleared, lines


def _perimeter(bits):
    empty = FULL & ~bits
    return (
        (empty & COL_MASKS[0]).bit_count() + (empty & COL_MASKS[7]).bit_count()
        + (empty & ROW_MASKS[0]).bit_count() + (empty & ROW_MASKS[7]).bit_count()
        + (empty & (bits << 1) & NOT_COL0).bit_count() + (empty & (bits >> 1) & NOT_COL7).bit_count()
        + (empty & (bits << 8)).bit_count() + (empty & (bits >> 8)).bit_count()
    )


def _enclosed(bits):
    empty = FULL & ~bits
    reach = empty & BORDER
    while True:
        grow = (reach | ((reach << 1) & NOT_COL0) | ((reach >> 1) & NOT_COL7)
                | (reach << 8) | (reach >> 8)) & empty
        if grow == reach:
            return (empty & ~reach).bit_count()
        reach = grow


TRAY_BEAM = 40
TRAY_FINALS_CROWDED = 20
TRAY_FINALS_OPEN = 8
TRAY_CROWDED_FREE = 22
TRAY_DFS_BUDGET = 400
TRAY_LINE_W = 4.2
TRAY_PERIMETER_W = 0.2
TRAY_ENCLOSED_W = 0.75
TRAY_RISK_W = 400.0
HARD_TYPES = (3, 4, 6, 7, 10)

_POSE_MASKS = [list(_piece_placements(piece).values()) for piece in PIECE_POOL]
_HARD_POSES = [pose for t in HARD_TYPES for pose in PIECE_TYPES[t]]
_HARD_POSE_WEIGHT = {
    pose: 1 / (len(HARD_TYPES) * len(PIECE_TYPES[t])) for t in HARD_TYPES for pose in PIECE_TYPES[t]
}


def _orderings(multiset):
    return math.factorial(3) // math.prod(math.factorial(c) for c in Counter(multiset).values())


_HARD_MULTISETS = [
    (ms, _orderings(ms) * math.prod(_HARD_POSE_WEIGHT[p] for p in ms))
    for ms in combinations_with_replacement(_HARD_POSES, 3)
]


class _TrayBudget(Exception):
    pass


def _tray_playable(board, poses):
    budget = [TRAY_DFS_BUDGET]
    seen = set()

    def rec(b, rem):
        if not rem:
            return True
        key = (b, rem)
        if key in seen:
            return False
        seen.add(key)
        budget[0] -= 1
        if budget[0] < 0:
            raise _TrayBudget
        for j, pose in enumerate(rem):
            if j and rem[j - 1] == pose:
                continue
            rest = rem[:j] + rem[j + 1:]
            for mask in _POSE_MASKS[pose]:
                if (b & mask) == 0 and rec(_clear_lines(b | mask)[0], rest):
                    return True
        return False

    try:
        return rec(board, tuple(sorted(poses)))
    except _TrayBudget:
        return True


def _hard_risk(board):
    alive = {pose: any((board & mask) == 0 for mask in _POSE_MASKS[pose]) for pose in _HARD_POSES}
    return sum(
        weight for ms, weight in _HARD_MULTISETS
        if not (any(alive[p] for p in ms) and _tray_playable(board, ms))
    )


def _final_value(board, rank):
    return rank - TRAY_ENCLOSED_W * _enclosed(board) - TRAY_RISK_W * _hard_risk(board)


class SearchPolicy:
    """Przeszukuje klocki tacki i ocenia koniec tacki liniami, obwodem, zalaniem i ryzykiem następnej."""

    name = "tray_search"

    def reset(self, game_seed):
        self.queue = []

    def act(self, game, actions):
        if self.queue and self.queue[0] in actions:
            return self.queue.pop(0)
        slots = [(i, p.index) for i, p in enumerate(game.pieces) if p is not None]
        moves = self._plan(_bitboard(game.board.grid), slots)
        self.queue = list(moves[1:]) if len(moves) == len(slots) else []
        return moves[0] if moves and moves[0] in actions else actions[0]

    def _plan(self, board, slots):
        full = (1 << len(slots)) - 1
        states = {(board, 0): (0.0, 0, 0, ())}
        for _ in slots:
            nxt = {}
            for (b, used), (_rank, lines_acc, ghost, moves) in states.items():
                for si, (slot, pose) in enumerate(slots):
                    bit = 1 << si
                    if used & bit:
                        continue
                    for (x, y), mask in _piece_placements(PIECE_POOL[pose]).items():
                        if b & mask:
                            continue
                        pre = b | mask
                        after, lines = _clear_lines(pre)
                        ghost_after = ghost | (pre & ~after)
                        acc = lines_acc + lines
                        rank = TRAY_LINE_W * acc - TRAY_PERIMETER_W * _perimeter(after | ghost_after)
                        key = (after, used | bit)
                        current = nxt.get(key)
                        if current is None or rank > current[0]:
                            nxt[key] = (rank, acc, ghost_after, moves + ((slot, x, y),))
            if not nxt:
                break
            states = dict(sorted(nxt.items(), key=lambda kv: -kv[1][0])[:TRAY_BEAM])
        complete = [(key[0], value) for key, value in states.items() if key[1] == full]
        if not complete:
            return max(states.values(), key=lambda v: v[0])[3] if states else ()
        free = 64 - board.bit_count()
        count = TRAY_FINALS_CROWDED if free <= TRAY_CROWDED_FREE else TRAY_FINALS_OPEN
        finals = sorted(complete, key=lambda c: -c[1][0])[:count]
        return max(finals, key=lambda c: _final_value(c[0], c[1][0]))[1][3]


def build(weights):
    return SearchPolicy()
