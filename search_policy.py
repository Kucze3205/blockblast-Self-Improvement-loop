"""Polityka wiązkowa po tacce: plan postawień na tackę, liść z karą za zajętość i ryzyko trudnych tacek."""
import itertools
import math
from collections import Counter

from pieces import PIECE_POOL, PIECE_TYPES

BOARD = 8
FULL = (1 << (BOARD * BOARD)) - 1

BEAM = 40
FINAL_SMALL = 8
FINAL_TIGHT = 20
TIGHT_FREE_CELLS = 22
HARD_TYPES = [4, 6, 7, 10, 9]
TRAY_BUDGET = 400

W_LINE = 4.2
W_OCC = 1.4
W_ISO = 0.75
W_EDGE = 1.5
W_BORDER = 2.0
W_DEAD = 12.3
W_MATCH_CUBE = 400.0
W_MATCH_LIN = 80.0
W_HARD = 500.0


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


HARD_POSES = sorted(p for t in HARD_TYPES for p in PIECE_TYPES[t])
HARD_SHARE = {p: 1 / (len(HARD_TYPES) * len(PIECE_TYPES[t])) for t in HARD_TYPES for p in PIECE_TYPES[t]}
HARD_TRAYS = [
    (poses, math.factorial(3) // math.prod(math.factorial(c) for c in Counter(poses).values())
     * math.prod(HARD_SHARE[p] for p in poses))
    for poses in itertools.combinations_with_replacement(HARD_POSES, 3)
]


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


def _tray_ok(board, poses, clear, seen, budget):
    if not poses:
        return True
    if (board, poses) in seen:
        return False
    seen.add((board, poses))
    budget[0] -= 1
    if budget[0] < 0:
        raise _Budget
    for i, pose in enumerate(poses):
        if i and poses[i - 1] == pose:
            continue
        rest = poses[:i] + poses[i + 1:]
        for mask, _, _ in POSITIONS[pose]:
            if board & mask:
                continue
            nxt = _place(board, mask)[0] if clear else board | mask
            if _tray_ok(nxt, rest, clear, seen, budget):
                return True
    return False


def _tray_fits(board, poses, limit=math.inf):
    # Ułożenie bez czyszczenia jest też ułożeniem z czyszczeniem, więc to tylko szybka ścieżka.
    # Wyczerpany budżet liczy tacę jako mieszczącą się, więc ryzyko jest co najwyżej zaniżone.
    budget = [limit]
    poses = tuple(sorted(poses))
    try:
        return _tray_ok(board, poses, False, set(), budget) or _tray_ok(board, poses, True, set(), budget)
    except _Budget:
        return True


def _hard_risk(board):
    return sum(weight for poses, weight in HARD_TRAYS if not _tray_fits(board, poses, TRAY_BUDGET))


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


def _base_penalty(board):
    dead = 0
    fraction = 0.0
    for poses in PIECE_TYPES:
        fits = sum(1 for p in poses if _fits(board, p))
        if fits == 0:
            dead += 1
        fraction += fits / len(poses)
    avg = fraction / len(PIECE_TYPES)
    return (
        _shape_cost(board)
        + W_DEAD * dead
        + W_MATCH_CUBE * (1 - avg) ** 3
        + W_MATCH_LIN * (1 - avg)
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
        if not children:
            break
        ranked = sorted(children.values(), key=lambda c: c[0], reverse=True)[:BEAM]
        states = [c[1:] for c in ranked]
    return states


def _choose_leaf(finalists):
    scored = []
    for i, leaf in enumerate(finalists):
        base = _base_penalty(leaf[0])
        scored.append((W_LINE * leaf[2] - base, i, base))
    scored.sort(key=lambda t: (-t[0], t[1]))
    best_value = best_i = None
    for bound, i, base in scored:
        if best_value is not None and bound < best_value:
            break
        leaf = finalists[i]
        value = W_LINE * leaf[2] - (base + W_HARD * _hard_risk(leaf[0]))
        if best_value is None or value > best_value or (value == best_value and i < best_i):
            best_value, best_i = value, i
    return finalists[best_i]


class SearchPolicy:
    name = "search"

    def reset(self, game_seed):
        pass

    def act(self, game, actions):
        board = _board_bits(game.board.grid)
        slots = [s for s, piece in enumerate(game.pieces) if piece is not None]
        pose_of = {s: game.pieces[s].index for s in slots}
        leaves = _beam(board, slots, pose_of)

        free = BOARD * BOARD - board.bit_count()
        keep = FINAL_TIGHT if free <= TIGHT_FREE_CELLS else FINAL_SMALL
        finalists = sorted(leaves, key=lambda leaf: _cheap(leaf[0], leaf[2]), reverse=True)[:keep]
        return _choose_leaf(finalists)[3][0]
