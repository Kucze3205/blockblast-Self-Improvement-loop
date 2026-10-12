"""Przeszukanie tacki na bitboardach: wiązka po wszystkich kotwicach, ryzyko następnej tacki na finalistach."""
from pieces import PIECE_POOL, PIECE_TYPES

BEAM_WIDTH = 40
FINALISTS = 8
FINALISTS_TIGHT = 20
TIGHT_FREE_CELLS = 22
OCC_W = 1.4
LINE_W = 4.2
ISO_W = 0.75
TRANS_W = 1.5
EDGE_W = 2.0
DEAD_W = 12.3
DEATH_W = 400.0
SAMPLES = 256

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


def _dead_types(bb):
    free = FULL ^ bb
    fit_types = {POSE_TYPE[p] for p in range(N_POSES) if _fits(free, p)}
    return N_TYPES - len(fit_types)


def _completable(bb, poses):
    if not poses:
        return True
    free = FULL ^ bb
    for k, pose in enumerate(poses):
        anchors = _fits(free, pose)
        if not anchors:
            continue
        rest = poses[:k] + poses[k + 1:]
        for anchor in _bits(anchors):
            if _completable(_place(bb, pose, anchor)[0], rest):
                return True
    return False


def sample_trays(rng):
    return [tuple(rng.choice(rng.choice(PIECE_TYPES)) for _ in range(3)) for _ in range(SAMPLES)]


def _none_rate(bb):
    free = FULL ^ bb
    miss = sum(sum(1 for pose in ids if not _fits(free, pose)) / len(ids) for ids in PIECE_TYPES) / N_TYPES
    return miss ** 3


def _stuck_share(bb, samples):
    free = FULL ^ bb
    stuck = sum(1 for tray in samples if any(_fits(free, pose) for pose in tray) and not _completable(bb, tray))
    return stuck / len(samples)


def _cheap_value(bb, lines):
    empty_edges = ((FULL ^ bb) & EDGE).bit_count()
    return (-OCC_W * bb.bit_count() + LINE_W * lines - ISO_W * _isolated(bb)
            - TRANS_W * _transitions(bb) - EDGE_W * empty_edges)


def best_move(bb, tray, samples):
    tray = tuple(tray)
    beam = [(bb, tray, None, 0)]
    ends, dead = [], []
    while beam:
        children = []
        for board, rem, first, lines in beam:
            free = FULL ^ board
            for k, (slot, pose) in enumerate(rem):
                anchors = _fits(free, pose)
                if not anchors:
                    continue
                rest = rem[:k] + rem[k + 1:]
                for anchor in _bits(anchors):
                    nxt, cleared = _place(board, pose, anchor)
                    total = lines + cleared
                    move = first or (slot, anchor)
                    if not rest:
                        ends.append((_cheap_value(nxt, total), nxt, move))
                    elif not any(_fits(FULL ^ nxt, other) for _, other in rest):
                        dead.append((len(tray) - len(rest), move))
                    else:
                        children.append((_cheap_value(nxt, total), nxt, rest, total, move))
        children.sort(key=lambda child: child[0], reverse=True)
        beam, seen = [], set()
        for _, nxt, rest, total, move in children:
            if (nxt, rest) in seen:
                continue
            seen.add((nxt, rest))
            beam.append((nxt, rest, move, total))
            if len(beam) == BEAM_WIDTH:
                break

    if not ends:
        return max(dead, key=lambda leaf: leaf[0])[1]
    width = FINALISTS_TIGHT if 64 - bb.bit_count() <= TIGHT_FREE_CELLS else FINALISTS
    ends.sort(key=lambda end: end[0], reverse=True)
    finalists, boards = [], set()
    for end in ends:
        if end[1] not in boards:
            boards.add(end[1])
            finalists.append(end)
            if len(finalists) == width:
                break
    best_score, best = None, None
    for value, nxt, move in finalists:
        score = value - DEAD_W * _dead_types(nxt) - DEATH_W * (_none_rate(nxt) + _stuck_share(nxt, samples))
        if best_score is None or score > best_score:
            best_score, best = score, move
    return best
