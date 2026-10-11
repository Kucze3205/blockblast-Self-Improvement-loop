"""
Polityka wiązkowa po tacce: plan postawień na tackę, liść z kształtem planszy,
kara za dopasowanie typów i dokładne ryzyko trudnych tacek.
"""
import math
from collections import Counter
from itertools import combinations_with_replacement

from pieces import PIECE_POOL, PIECE_TYPES

BOARD = 8
FULL = (1 << (BOARD * BOARD)) - 1

BEAM = 40
FINAL_SMALL = 8
FINAL_TIGHT = 20
TIGHT_FREE_CELLS = 22
DFS_BUDGET = 400
HARD_TYPES = (4, 6, 7, 10, 9)
MIXED_MAX_FREE = 40

DEFAULT_WEIGHTS = {
    "LINE_W": 4.2,
    "OCC_W": 1.4,
    "ISO_W": 0.75,
    "EDGE_W": 1.5,
    "BORDER_W": 2.0,
    "DEAD_W": 12.3,
    "FIT_W": 400.0,
    "FIT_MEAN_W": 80.0,
    "HARD_W": 500.0,
}


def _bit(r, c):
    return 1 << (r * BOARD + c)


ROW_MASKS = [sum(_bit(r, c) for c in range(BOARD)) for r in range(BOARD)]
COL_MASKS = [sum(_bit(r, c) for r in range(BOARD)) for c in range(BOARD)]
BORDER_MASK = sum(
    _bit(r, c)
    for r in range(BOARD)
    for c in range(BOARD)
    if r in (0, BOARD - 1) or c in (0, BOARD - 1)
)
H_PAIRS = FULL & ~COL_MASKS[BOARD - 1]
V_PAIRS = FULL & ~ROW_MASKS[BOARD - 1]


def _pc(x):
    return bin(x).count("1")


def _positions(shape):
    h, w = len(shape), len(shape[0])
    cells = [(dy, dx) for dy, row in enumerate(shape) for dx, v in enumerate(row) if v]
    out = []
    for y in range(BOARD - h + 1):
        for x in range(BOARD - w + 1):
            mask = 0
            for dy, dx in cells:
                mask |= _bit(y + dy, x + dx)
            out.append((mask, x, y))
    return out


POSITIONS = [_positions(piece.shape) for piece in PIECE_POOL]


def _board_bits(grid):
    bits = 0
    for r in range(BOARD):
        for c in range(BOARD):
            if grid[r][c]:
                bits |= _bit(r, c)
    return bits


def _place(board, mask):
    filled = board | mask
    rows = [m for m in ROW_MASKS if filled & m == m]
    cols = [m for m in COL_MASKS if filled & m == m]
    for m in rows + cols:
        filled &= ~m
    return filled, len(rows) + len(cols)


def _fits(board, pose):
    return any((board & mask) == 0 for mask, _, _ in POSITIONS[pose])


class _Budget(Exception):
    pass


def _tray_ok(board, poses):
    left = [DFS_BUDGET]
    seen = set()

    def rec(b, rem):
        if not rem:
            return True
        if (b, rem) in seen:
            return False
        seen.add((b, rem))
        left[0] -= 1
        if left[0] < 0:
            raise _Budget
        for j, p in enumerate(rem):
            if j and rem[j - 1] == p:
                continue
            rest = rem[:j] + rem[j + 1:]
            for mask, _, _ in POSITIONS[p]:
                if b & mask:
                    continue
                if rec(_place(b, mask)[0], rest):
                    return True
        return False

    try:
        return rec(board, tuple(sorted(poses)))
    except _Budget:
        return True


def _orderings(ms):
    return math.factorial(3) // math.prod(math.factorial(c) for c in Counter(ms).values())


def _hard_multisets():
    poses = [p for t in HARD_TYPES for p in PIECE_TYPES[t]]
    out = []
    for ms in combinations_with_replacement(poses, 3):
        weight = float(_orderings(ms))
        for p in ms:
            weight /= len(HARD_TYPES) * len(PIECE_TYPES[PIECE_POOL[p].type_index])
        out.append((ms, weight))
    return out


HARD_MULTISETS = _hard_multisets()
HARD_SCALE = (len(PIECE_TYPES) / len(HARD_TYPES)) ** 3


def _hard_risk(board):
    return sum(weight for ms, weight in HARD_MULTISETS if not _tray_ok(board, ms))


def _mixed_weight(ms):
    weight = HARD_SCALE * _orderings(ms)
    for p in ms:
        weight /= len(PIECE_TYPES) * len(PIECE_TYPES[PIECE_POOL[p].type_index])
    return weight


def _mixed_multisets():
    hard = sorted({p for t in HARD_TYPES for p in PIECE_TYPES[t]})
    other = [p for p in range(len(PIECE_POOL)) if p not in hard]
    out = []
    for pair in combinations_with_replacement(hard, 2):
        for x in other:
            ms = tuple(sorted(pair + (x,)))
            out.append((ms, _mixed_weight(ms)))
    return out


MIXED_MULTISETS = _mixed_multisets()


def _mixed_risk(board):
    return sum(weight for ms, weight in MIXED_MULTISETS if not _tray_ok(board, ms))


def _shape_cost(board, w):
    free = ~board & FULL
    edges = _pc((board ^ (board >> 1)) & H_PAIRS) + _pc((board ^ (board >> BOARD)) & V_PAIRS)
    # Poza planszą liczy się jak zajęte, żeby brzeg nie robił z pól przy ścianie dziur.
    walled = (
        (((board << 1) & FULL) | COL_MASKS[0])
        & ((board >> 1) | COL_MASKS[BOARD - 1])
        & (((board << BOARD) & FULL) | ROW_MASKS[0])
        & ((board >> BOARD) | ROW_MASKS[BOARD - 1])
    )
    iso = _pc(walled & free)
    empty_border = _pc(free & BORDER_MASK)
    return (
        w["OCC_W"] * _pc(board)
        + w["ISO_W"] * iso
        + w["EDGE_W"] * edges
        + w["BORDER_W"] * empty_border
    )


def _cheap(board, lines, w):
    return w["LINE_W"] * lines - _shape_cost(board, w)


def _penalty(board, w):
    dead = 0
    fraction = 0.0
    for group in PIECE_TYPES:
        fits = sum(1 for p in group if _fits(board, p))
        if fits == 0:
            dead += 1
        fraction += fits / len(group)
    avg = fraction / len(PIECE_TYPES)
    hard = _hard_risk(board)
    # Przy wielu wolnych polach masa mieszana jest pomijalna, a koszt DFS na liść nie.
    if BOARD * BOARD - _pc(board) <= MIXED_MAX_FREE:
        hard += _mixed_risk(board)
    return (
        _shape_cost(board, w)
        + w["DEAD_W"] * dead
        + w["FIT_W"] * (1 - avg) ** 3
        + w["FIT_MEAN_W"] * (1 - avg)
        + w["HARD_W"] * hard
    )


def _beam(board, slots, pose_of, w):
    states = [(board, 0, 0, ())]
    for _ in slots:
        children = {}
        for b, used, lines, acts in states:
            for s in slots:
                bit = 1 << s
                if used & bit:
                    continue
                for mask, x, y in POSITIONS[pose_of[s]]:
                    if b & mask:
                        continue
                    nb, cleared = _place(b, mask)
                    total = lines + cleared
                    key = (nb, used | bit)
                    score = _cheap(nb, total, w)
                    old = children.get(key)
                    if old is None or score > old[0]:
                        children[key] = (score, nb, used | bit, total, acts + ((s, x, y),))
        ranked = sorted(children.values(), key=lambda c: c[0], reverse=True)[:BEAM]
        states = [c[1:] for c in ranked]
    return states


class SearchPolicy:
    name = "search"

    def __init__(self, weights=None):
        self.w = {**DEFAULT_WEIGHTS, **(weights or {})}

    def reset(self, game_seed):
        pass

    def act(self, game, actions):
        board = _board_bits(game.board.grid)
        slots = [s for s, piece in enumerate(game.pieces) if piece is not None]
        pose_of = {s: game.pieces[s].index for s in slots}
        w = self.w
        leaves = _beam(board, slots, pose_of, w)
        if not leaves:
            return actions[0]
        free = BOARD * BOARD - _pc(board)
        keep = FINAL_TIGHT if free <= TIGHT_FREE_CELLS else FINAL_SMALL
        finalists = sorted(leaves, key=lambda leaf: _cheap(leaf[0], leaf[2], w), reverse=True)[:keep]
        best = max(finalists, key=lambda leaf: w["LINE_W"] * leaf[2] - _penalty(leaf[0], w))
        return best[3][0]
