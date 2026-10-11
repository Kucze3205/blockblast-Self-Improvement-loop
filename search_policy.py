"""Polityka wiązkowa po tacce: plan postawień na tackę, liść z karą za zajętość i ryzyko trudnych tacek."""
import random
from itertools import combinations_with_replacement
from math import factorial, prod

from pieces import PIECE_POOL, PIECE_TYPES

BOARD = 8
FULL = (1 << (BOARD * BOARD)) - 1

BEAM = 40
FINAL_SMALL = 8
FINAL_TIGHT = 20
TIGHT_FREE_CELLS = 22
HARD_TYPES = [4, 6, 7, 10, 9]
HARD_MULTISETS = [
    (ms, factorial(3) // prod(factorial(ms.count(t)) for t in set(ms)) / len(HARD_TYPES) ** 3)
    for ms in combinations_with_replacement(HARD_TYPES, 3)
]

W_LINE = 4.2
W_OCC = 1.4
W_ISO = 0.75
W_EDGE = 1.5
W_BORDER = 2.0
W_DEAD = 12.3
W_MATCH_CUBE = 400.0
W_MATCH_LIN = 80.0
W_HARD = 400.0


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

POSITIONS = []
for _piece in PIECE_POOL:
    _h, _w = len(_piece.shape), len(_piece.shape[0])
    _cells = [(dy, dx) for dy, row in enumerate(_piece.shape) for dx, v in enumerate(row) if v]
    _options = []
    for y in range(BOARD - _h + 1):
        for x in range(BOARD - _w + 1):
            mask = 0
            for dy, dx in _cells:
                mask |= _bit(y + dy, x + dx)
            _options.append((mask, x, y))
    POSITIONS.append(_options)


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


def _tray_fits(board, poses):
    if not poses:
        return True
    for i, pose in enumerate(poses):
        rest = poses[:i] + poses[i + 1:]
        for mask, _, _ in POSITIONS[pose]:
            if (board & mask) == 0 and _tray_fits(_place(board, mask)[0], rest):
                return True
    return False


def _shape_cost(board):
    free = ~board & FULL
    edges = (
        ((board ^ (board >> 1)) & H_PAIRS).bit_count()
        + ((board ^ (board >> BOARD)) & V_PAIRS).bit_count()
    )
    # Poza planszą liczy się jak zajęte, żeby brzeg nie robił z pól przy ścianie dziur.
    walled = (
        (((board << 1) & FULL) | COL_MASKS[0])
        & ((board >> 1) | COL_MASKS[BOARD - 1])
        & (((board << BOARD) & FULL) | ROW_MASKS[0])
        & ((board >> BOARD) | ROW_MASKS[BOARD - 1])
    )
    iso = (walled & free).bit_count()
    empty_border = (free & BORDER_MASK).bit_count()
    return W_OCC * board.bit_count() + W_ISO * iso + W_EDGE * edges + W_BORDER * empty_border


def _cheap(board, lines):
    return W_LINE * lines - _shape_cost(board)


def _penalty(board, hard_trays):
    dead = 0
    fraction = 0.0
    for poses in PIECE_TYPES:
        fits = sum(1 for p in poses if _fits(board, p))
        if fits == 0:
            dead += 1
        fraction += fits / len(poses)
    avg = fraction / len(PIECE_TYPES)

    lost = sum(w for tray, w in hard_trays if not _tray_fits(board, tray))
    return (
        _shape_cost(board)
        + W_DEAD * dead
        + W_MATCH_CUBE * (1 - avg) ** 3
        + W_MATCH_LIN * (1 - avg)
        + W_HARD * lost
    )


def _beam(board, slots, pose_of):
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
                    score = _cheap(nb, total)
                    old = children.get(key)
                    if old is None or score > old[0]:
                        children[key] = (score, nb, used | bit, total, acts + ((s, x, y),))
        ranked = sorted(children.values(), key=lambda c: c[0], reverse=True)[:BEAM]
        states = [c[1:] for c in ranked]
    return states


class SearchPolicy:
    name = "search"

    def reset(self, game_seed):
        self.rng = random.Random(f"search:{game_seed}")

    def act(self, game, actions):
        board = _board_bits(game.board.grid)
        slots = [s for s, piece in enumerate(game.pieces) if piece is not None]
        pose_of = {s: game.pieces[s].index for s in slots}
        hard_trays = self._hard_trays()

        leaves = _beam(board, slots, pose_of)
        if not leaves:
            return actions[0]

        free = BOARD * BOARD - board.bit_count()
        keep = FINAL_TIGHT if free <= TIGHT_FREE_CELLS else FINAL_SMALL
        finalists = sorted(leaves, key=lambda leaf: _cheap(leaf[0], leaf[2]), reverse=True)[:keep]
        best = max(finalists, key=lambda leaf: W_LINE * leaf[2] - _penalty(leaf[0], hard_trays))
        return best[3][0]

    def _hard_trays(self):
        poses = {t: [self.rng.choice(PIECE_TYPES[t]) for _ in range(3)] for t in HARD_TYPES}
        trays = []
        for multiset, weight in HARD_MULTISETS:
            used = dict.fromkeys(HARD_TYPES, 0)
            tray = []
            for t in multiset:
                tray.append(poses[t][used[t]])
                used[t] += 1
            trays.append((tray, weight))
        return trays
