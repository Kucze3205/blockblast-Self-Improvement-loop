"""Polityka wiązkowa po tacce: plan postawień na tackę, liść z karą za zajętość i ryzyko trudnych tacek."""
import random

from pieces import PIECE_POOL, PIECE_TYPES

BOARD = 8
FULL = (1 << (BOARD * BOARD)) - 1

BEAM = 40
FINAL_SMALL = 8
FINAL_TIGHT = 20
TIGHT_FREE_CELLS = 22
RISK_TRAYS = 16
HARD_TYPES = [4, 6, 7, 10, 9]

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

NEIGHBOURS = [[] for _ in range(BOARD * BOARD)]
for _r in range(BOARD):
    for _c in range(BOARD):
        for _dr, _dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            _nr, _nc = _r + _dr, _c + _dc
            if 0 <= _nr < BOARD and 0 <= _nc < BOARD:
                NEIGHBOURS[_r * BOARD + _c].append(_nr * BOARD + _nc)

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


def _cheap(board, lines):
    return W_LINE * lines - W_OCC * board.bit_count()


def _penalty(board, hard_trays):
    occ = board.bit_count()
    empty_border = (~board & BORDER_MASK).bit_count()
    iso = edges = 0
    for i in range(BOARD * BOARD):
        if board >> i & 1:
            edges += sum(1 for j in NEIGHBOURS[i] if not board >> j & 1)
        elif all(board >> j & 1 for j in NEIGHBOURS[i]):
            iso += 1

    dead = 0
    fraction = 0.0
    for poses in PIECE_TYPES:
        fits = sum(1 for p in poses if _fits(board, p))
        if fits == 0:
            dead += 1
        fraction += fits / len(poses)
    avg = fraction / len(PIECE_TYPES)

    lost = sum(1 for tray in hard_trays if not _tray_fits(board, tray))
    return (
        W_OCC * occ
        + W_ISO * iso
        + W_EDGE * edges
        + W_BORDER * empty_border
        + W_DEAD * dead
        + W_MATCH_CUBE * (1 - avg) ** 3
        + W_MATCH_LIN * (1 - avg)
        + W_HARD * lost / len(hard_trays)
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
        hard_trays = [self._hard_tray() for _ in range(RISK_TRAYS)]

        leaves = _beam(board, slots, pose_of)
        if not leaves:
            return actions[0]

        free = BOARD * BOARD - board.bit_count()
        keep = FINAL_TIGHT if free <= TIGHT_FREE_CELLS else FINAL_SMALL
        finalists = sorted(leaves, key=lambda leaf: _cheap(leaf[0], leaf[2]), reverse=True)[:keep]
        best = max(finalists, key=lambda leaf: W_LINE * leaf[2] - _penalty(leaf[0], hard_trays))
        return best[3][0]

    def _hard_tray(self):
        tray = []
        for _ in range(3):
            t = self.rng.choice(HARD_TYPES)
            tray.append(self.rng.choice(PIECE_TYPES[t]))
        return tray
