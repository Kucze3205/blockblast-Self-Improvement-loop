"""
Wiązka po tacce na bitboardach. Bit = wiersz * 8 + kolumna, kotwica klocka = lewy-górny róg.
"""
from collections import Counter
from itertools import combinations_with_replacement
from math import factorial, prod

from pieces import PIECE_POOL, PIECE_TYPES

FULL = (1 << 64) - 1
ROW = [0xFF << (8 * r) for r in range(8)]
COL = [sum(1 << (8 * r + c) for r in range(8)) for c in range(8)]
NOT_COL0 = FULL & ~COL[0]
NOT_COL7 = FULL & ~COL[7]
RING = ROW[0] | ROW[7] | COL[0] | COL[7]
ROWS_0_6 = FULL & ~ROW[7]

HARD_TYPES = (3, 4, 7, 6, 10)  # beam4, beam5, square3, rect23, corner5
BEAM = 120
W_OCC, W_ISO, W_LINE = 1.4, 0.75, 4.2
W_TRANS, W_BORDER = 1.5, 2.0
W_DEAD = 66.0  # 12.3 za w pełni martwy typ = 66 * P(tacka ma martwy klocek)
W_HARD = 400.0
JOINT_BUDGET = 200


def _pose(shape):
    h, w = len(shape), len(shape[0])
    cells = [dy * 8 + dx for dy, row in enumerate(shape) for dx, v in enumerate(row) if v]
    body = 0
    for off in cells:
        body |= 1 << off
    valid = 0
    for y in range(8 - h + 1):
        for x in range(8 - w + 1):
            valid |= 1 << (y * 8 + x)
    return body, valid, cells


POSES = [_pose(piece.shape) for piece in PIECE_POOL]
SLOT_P = [0.0] * len(PIECE_POOL)
for _poses in PIECE_TYPES:
    for _p in _poses:
        SLOT_P[_p] = 1 / (15 * len(_poses))

HARD_POSES = [p for t in HARD_TYPES for p in PIECE_TYPES[t]]
HARD_MULTISETS = []
for _combo in combinations_with_replacement(HARD_POSES, 3):
    _perms = 6 // prod(factorial(c) for c in Counter(_combo).values())
    _weight = _perms * SLOT_P[_combo[0]] * SLOT_P[_combo[1]] * SLOT_P[_combo[2]]
    HARD_MULTISETS.append((_weight, _combo))


def occupancy(grid):
    occ = 0
    for r, row in enumerate(grid):
        for c, v in enumerate(row):
            if v:
                occ |= 1 << (r * 8 + c)
    return occ


def _fit(occ, pose):
    _, m, cells = POSES[pose]
    free = ~occ & FULL
    for off in cells:
        m &= free >> off
    return m


def _place(occ, pose, anchor):
    return occ | (POSES[pose][0] << anchor)


def _settle(occ):
    clear, lines = 0, 0
    for m in ROW:
        if (occ & m) == m:
            clear |= m
            lines += 1
    for m in COL:
        if (occ & m) == m:
            clear |= m
            lines += 1
    return occ & ~clear, lines


def _pockets(occ):
    free = ~occ & FULL
    near = ((free << 1) & NOT_COL0) | ((free >> 1) & NOT_COL7) | ((free << 8) & FULL) | (free >> 8)
    return (free & ~near).bit_count()


def _transitions(occ):
    empty = FULL & ~occ
    return (
        ((occ ^ (occ >> 1)) & ~COL[7]).bit_count()
        + (empty & COL[0]).bit_count()
        + (empty & COL[7]).bit_count()
        + ((occ ^ (occ >> 8)) & ROWS_0_6).bit_count()
        + (empty & ROW[0]).bit_count()
        + (empty & ROW[7]).bit_count()
    )


def _leaf(occ, lines):
    border = (FULL & ~occ & RING).bit_count()
    return (
        W_LINE * lines
        - W_OCC * occ.bit_count()
        - W_ISO * _pockets(occ)
        - W_TRANS * _transitions(occ)
        - W_BORDER * border
    )


def _dead_tray_prob(occ):
    q = 0.0
    for poses in PIECE_TYPES:
        dead = sum(1 for p in poses if not _fit(occ, p))
        q += dead / (15 * len(poses))
    return 1 - (1 - q) ** 3


def _joint_playable(occ, poses, budget):
    if not poses:
        return True
    if budget[0] <= 0:
        return False
    budget[0] -= 1
    for i, p in enumerate(poses):
        if i and poses[i - 1] == p:
            continue
        rest = poses[:i] + poses[i + 1:]
        m = _fit(occ, p)
        while m:
            low = m & -m
            m ^= low
            nxt, _ = _settle(_place(occ, p, low.bit_length() - 1))
            if _joint_playable(nxt, rest, budget):
                return True
    return False


def _hard_risk(occ):
    alive = {p: _fit(occ, p) for p in HARD_POSES}
    risk = 0.0
    for weight, poses in HARD_MULTISETS:
        if any(not alive[p] for p in poses):
            continue
        if not _joint_playable(occ, poses, [JOINT_BUDGET]):
            risk += weight
    return risk


def _beam(occ, pieces):
    level = [(_leaf(occ, 0), 0, occ, 0, None)]
    for _ in range(len(pieces)):
        best = {}
        for _score, lines, o, used, first in level:
            for k, (slot, pose) in enumerate(pieces):
                bit = 1 << k
                if used & bit:
                    continue
                body = POSES[pose][0]
                m = _fit(o, pose)
                while m:
                    low = m & -m
                    m ^= low
                    anchor = low.bit_length() - 1
                    o2, cleared = _settle(o | (body << anchor))
                    l2 = lines + cleared
                    u2 = used | bit
                    score = _leaf(o2, l2)
                    cur = best.get((o2, u2))
                    if cur is None or score > cur[0]:
                        best[(o2, u2)] = (score, l2, o2, u2, first or (slot, anchor))
        if not best:
            return False, level
        level = sorted(best.values(), key=lambda s: s[0], reverse=True)[:BEAM]
    return True, level


class TraySearchPolicy:
    name = "tray-search"

    def reset(self, game_seed):
        pass

    def act(self, game, actions):
        occ = occupancy(game.board.grid)
        pieces = [(i, piece.index) for i, piece in enumerate(game.pieces) if piece is not None]
        complete, states = _beam(occ, pieces)
        if not complete:
            slot, anchor = states[0][4]
            return (slot, anchor % 8, anchor // 8)

        width = 20 if 64 - occ.bit_count() <= 22 else 8
        best_value, best_first = None, None
        for score, _lines, o2, _used, first in states[:width]:
            value = score - W_DEAD * _dead_tray_prob(o2) - W_HARD * _hard_risk(o2)
            if best_value is None or value > best_value:
                best_value, best_first = value, first
        slot, anchor = best_first
        return (slot, anchor % 8, anchor // 8)
