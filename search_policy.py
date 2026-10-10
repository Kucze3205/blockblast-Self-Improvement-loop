"""
Polityka przeszukująca tackę: wiązka po postawieniach klocków tacki na bitboardach,
ocena końcowej planszy (cechy liścia, dopasowanie typów, ryzyko trudnych tacek).
"""
import math
from collections import Counter
from itertools import combinations_with_replacement

from pieces import PIECE_POOL, PIECE_TYPES

FULL = (1 << 64) - 1
COL0 = sum(1 << (8 * y) for y in range(8))
COL7 = COL0 << 7
ROW0 = 0xFF
ROW7 = 0xFF << 56
RING = ROW0 | ROW7 | COL0 | COL7
ROWS_0_6 = FULL & ~ROW7
ROW_MASKS = [0xFF << (8 * y) for y in range(8)]
COL_MASKS = [COL0 << x for x in range(8)]

BEAM = 40
FINAL_CROWDED = 20
FINAL_OPEN = 8
CROWDED_FREE = 22
DFS_BUDGET = 400
HARD_TYPES = (3, 4, 7, 6, 10)
HARD_W = 400.0
FIT_W = 400.0
FIT_MEAN_W = 80.0
DEAD_W = 12.3
LINE_W = 4.2
OCC_W = 1.4
POCKET_W = 0.75
TRANS_W = 1.5
BORDER_W = 2.0


def _placements(shape):
    h, w = len(shape), len(shape[0])
    out = []
    for y in range(8 - h + 1):
        for x in range(8 - w + 1):
            mask = 0
            for dy, row in enumerate(shape):
                for dx, cell in enumerate(row):
                    if cell:
                        mask |= 1 << ((y + dy) * 8 + x + dx)
            out.append((x, y, mask))
    return out


POSES = [_placements(piece.shape) for piece in PIECE_POOL]
HARD_POSES = [p for t in HARD_TYPES for p in PIECE_TYPES[t]]
HARD_POSE_WEIGHT = {p: 1 / (len(HARD_TYPES) * len(PIECE_TYPES[t])) for t in HARD_TYPES for p in PIECE_TYPES[t]}


def _orderings(ms):
    return math.factorial(3) // math.prod(math.factorial(c) for c in Counter(ms).values())


HARD_MULTISETS = [
    (ms, _orderings(ms) * math.prod(HARD_POSE_WEIGHT[p] for p in ms))
    for ms in combinations_with_replacement(HARD_POSES, 3)
]


def _pc(x):
    return bin(x).count("1")


def _to_bits(grid):
    bits = 0
    for y, row in enumerate(grid):
        for x, cell in enumerate(row):
            if cell:
                bits |= 1 << (8 * y + x)
    return bits


def _clear(board):
    cleared = 0
    lines = 0
    for m in ROW_MASKS:
        if (board & m) == m:
            cleared |= m
            lines += 1
    for m in COL_MASKS:
        if (board & m) == m:
            cleared |= m
            lines += 1
    return board & ~cleared, lines


def _cheap(b):
    e = FULL & ~b
    bl = ((b << 1) & FULL & ~COL0) | COL0
    br = ((b >> 1) & ~COL7) | COL7
    bu = ((b << 8) & FULL) | ROW0
    bd = (b >> 8) | ROW7
    pockets = _pc(e & ((bl & br & bu) | (bl & br & bd) | (bl & bu & bd) | (br & bu & bd)))
    trans = (
        _pc((b ^ (b >> 1)) & ~COL7)
        + _pc(e & COL0) + _pc(e & COL7)
        + _pc((b ^ (b >> 8)) & ROWS_0_6)
        + _pc(e & ROW0) + _pc(e & ROW7)
    )
    occ = 64 - _pc(e)
    return -OCC_W * occ - POCKET_W * pockets - TRANS_W * trans - BORDER_W * _pc(e & RING)


def _alive(b):
    return [any(not (b & m) for _, _, m in group) for group in POSES]


def _fit_penalty(alive):
    fracs = [sum(alive[p] for p in group) / len(group) for group in PIECE_TYPES]
    alive_fracs = [f for f in fracs if f > 0]
    mean_alive = sum(alive_fracs) / len(alive_fracs) if alive_fracs else 0.0
    mean_all = sum(fracs) / len(fracs)
    dead = len(fracs) - len(alive_fracs)
    return FIT_W * (1 - mean_alive) ** 3 + FIT_MEAN_W * (1 - mean_all) + DEAD_W * dead


class _Budget(Exception):
    pass


def _tray_ok(board, poses):
    budget = [DFS_BUDGET]
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
            raise _Budget
        for j, p in enumerate(rem):
            if j and rem[j - 1] == p:
                continue
            rest = rem[:j] + rem[j + 1:]
            for _, _, m in POSES[p]:
                if b & m:
                    continue
                nb, _ = _clear(b | m)
                if rec(nb, rest):
                    return True
        return False

    try:
        return rec(board, tuple(sorted(poses)))
    except _Budget:
        return True


def _hard_risk(b, alive):
    risk = 0.0
    for ms, weight in HARD_MULTISETS:
        if not (any(alive[p] for p in ms) and _tray_ok(b, ms)):
            risk += weight
    return risk


def _final_value(b, rank):
    alive = _alive(b)
    return rank - _fit_penalty(alive) - HARD_W * _hard_risk(b, alive)


class SearchPolicy:
    name = "search"

    def reset(self, game_seed):
        self.queue = []

    def act(self, game, actions):
        if self.queue and self.queue[0] in actions:
            return self.queue.pop(0)
        board = _to_bits(game.board.grid)
        slots = [(i, p.index) for i, p in enumerate(game.pieces) if p is not None]
        self.queue = list(self._plan(board, slots))
        if self.queue and self.queue[0] in actions:
            return self.queue.pop(0)
        return actions[0]

    def _plan(self, board, slots):
        full = (1 << len(slots)) - 1
        states = {(board, 0): (0.0, 0, ())}
        for _ in slots:
            nxt = {}
            for (b, used), (_, acc, moves) in states.items():
                for si, (slot, pose) in enumerate(slots):
                    bit = 1 << si
                    if used & bit:
                        continue
                    for x, y, m in POSES[pose]:
                        if b & m:
                            continue
                        nb, lines = _clear(b | m)
                        nacc = acc + lines
                        rank = LINE_W * nacc + _cheap(nb)
                        key = (nb, used | bit)
                        cur = nxt.get(key)
                        if cur is None or rank > cur[0]:
                            nxt[key] = (rank, nacc, moves + ((slot, x, y),))
            if not nxt:
                break
            states = dict(sorted(nxt.items(), key=lambda kv: -kv[1][0])[:BEAM])

        complete = [(key[0], value) for key, value in states.items() if key[1] == full]
        if not complete:
            return max(states.values(), key=lambda v: v[0])[2] if states else ()
        free = 64 - _pc(board)
        count = FINAL_CROWDED if free <= CROWDED_FREE else FINAL_OPEN
        finals = sorted(complete, key=lambda c: -c[1][0])[:count]
        best = max(finals, key=lambda c: _final_value(c[0], c[1][0]))
        return best[1][2]
