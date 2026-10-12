"""Przeszukanie tacki na bitboardach: przycięte kotwice na klocek, pełne kombinacje, ryzyko następnej tacki."""
from pieces import PIECE_POOL, PIECE_TYPES

K_PER_PIECE = 4
OCC_W = 1.4
LINE_W = 4.2
ISO_W = 0.75
TRANS_W = 1.5
DEAD_W = 12.3
DEATH_W = 400.0

FULL = (1 << 64) - 1
ROW = [0xFF << (8 * r) for r in range(8)]
COL = [sum(1 << (8 * r + c) for r in range(8)) for c in range(8)]
NOT_COL0 = FULL ^ COL[0]
NOT_COL7 = FULL ^ COL[7]
EDGE = ROW[0] | ROW[7] | COL[0] | COL[7]

N_POSES = len(PIECE_POOL)
N_TYPES = len(PIECE_TYPES)
POSE_OFFS, POSE_PATTERN, POSE_ANCHORS = [], [], []
for piece in PIECE_POOL:
    h, w = len(piece.shape), len(piece.shape[0])
    offs = [dy * 8 + dx for dy, row in enumerate(piece.shape) for dx, cell in enumerate(row) if cell]
    anchors = 0
    for y in range(8 - h + 1):
        for x in range(8 - w + 1):
            anchors |= 1 << (y * 8 + x)
    POSE_OFFS.append(offs)
    POSE_PATTERN.append(sum(1 << o for o in offs))
    POSE_ANCHORS.append(anchors)

POSE_TYPE = [0] * N_POSES
for t, ids in enumerate(PIECE_TYPES):
    for p in ids:
        POSE_TYPE[p] = t


def board_bits(board):
    return sum(1 << (8 * y + x) for y, row in enumerate(board.grid) for x, cell in enumerate(row) if cell)


def _fits(free, pose):
    m = POSE_ANCHORS[pose]
    for o in POSE_OFFS[pose]:
        m &= free >> o
        if not m:
            return 0
    return m


def _bits(mask):
    while mask:
        low = mask & -mask
        yield low.bit_length() - 1
        mask ^= low


def _touch(bb):
    near = ((bb << 1) & NOT_COL0) | ((bb >> 1) & NOT_COL7) | (bb << 8) | (bb >> 8)
    return (FULL ^ bb) & (near | EDGE)


def _isolated(bb):
    free = FULL ^ bb
    near = ((free << 1) & NOT_COL0) | ((free >> 1) & NOT_COL7) | (free << 8) | (free >> 8)
    return (free & ~near).bit_count()


def _transitions(bb):
    horizontal = (bb ^ (bb >> 1)) & ~COL[7] & FULL
    vertical = (bb ^ (bb >> 8)) & ~ROW[7] & FULL
    return horizontal.bit_count() + vertical.bit_count()


def _place(bb, pose, anchor):
    bb |= POSE_PATTERN[pose] << anchor
    rows = [r for r in range(8) if (bb & ROW[r]) == ROW[r]]
    cols = [c for c in range(8) if (bb & COL[c]) == COL[c]]
    clear = 0
    for r in rows:
        clear |= ROW[r]
    for c in cols:
        clear |= COL[c]
    return bb & ~clear, len(rows) + len(cols)


def _death_risk(bb):
    free = FULL ^ bb
    type_fits = [0] * N_TYPES
    for p in range(N_POSES):
        if _fits(free, p):
            type_fits[POSE_TYPE[p]] += 1
    q = sum(type_fits[t] / (N_TYPES * len(PIECE_TYPES[t])) for t in range(N_TYPES))
    return q, type_fits.count(0)


def _leaf_value(bb, lines):
    q, dead = _death_risk(bb)
    return (-OCC_W * bb.bit_count() + LINE_W * lines - ISO_W * _isolated(bb)
            - TRANS_W * _transitions(bb) - DEAD_W * dead - DEATH_W * (1.0 - q) ** 3)


def _enumerate(bb, rem, lines, first, depth, alive, dead):
    if not rem:
        alive.append((bb, lines, first))
        return
    free = FULL ^ bb
    touch = _touch(bb)
    expanded = False
    for k, (tray_idx, pose) in enumerate(rem):
        anchors = _fits(free, pose)
        if not anchors:
            continue
        expanded = True
        pattern = POSE_PATTERN[pose]
        ranked = sorted(_bits(anchors), key=lambda a: -((pattern << a) & touch).bit_count())
        rest = rem[:k] + rem[k + 1:]
        for a in ranked[:K_PER_PIECE]:
            nb, nl = _place(bb, pose, a)
            _enumerate(nb, rest, lines + nl, first or (tray_idx, a), depth + 1, alive, dead)
    if not expanded:
        dead.append((depth, first))


def best_move(bb, tray):
    alive, dead = [], []
    _enumerate(bb, tray, 0, None, 0, alive, dead)
    if not alive:
        return max(dead, key=lambda leaf: leaf[0])[1]
    cache = {}
    best_value, best_first = None, None
    for leaf_bb, lines, first in alive:
        key = (leaf_bb, lines)
        if key not in cache:
            cache[key] = _leaf_value(leaf_bb, lines)
        if best_value is None or cache[key] > best_value:
            best_value, best_first = cache[key], first
    return best_first
