"""Wiązka po klockach tacki na bitboardach z karą za trudne tacki."""
import random

from pieces import PIECE_POOL, PIECE_TYPES

W = 8
FULL = (1 << (W * W)) - 1
ROWS = [0xFF << (W * y) for y in range(W)]
COLS = [sum(1 << (W * y + x) for y in range(W)) for x in range(W)]
NOT_COL0 = FULL & ~COLS[0]
NOT_COL7 = FULL & ~COLS[W - 1]
LE6 = FULL & ~COLS[W - 1]
LE5 = FULL & ~(COLS[W - 2] | COLS[W - 1])

HARD_TYPES = (4, 6, 7, 10, 9)  # beam5, rect23, square3, corner5, L
BEAM = 40
FINAL = 20
SAMPLES = 16
HARD_PENALTY = 500
TRAY_BUDGET = 400
OCC_W = 1.0
ISO_W = 4.0
HOLE_W = 4.0
SQ_W = 1.0
SQ_CAP = 8


def _placements(piece):
    h, w = len(piece.shape), len(piece.shape[0])
    cells = [(dy, dx) for dy, row in enumerate(piece.shape) for dx, cell in enumerate(row) if cell]
    out = []
    for y in range(W - h + 1):
        for x in range(W - w + 1):
            mask = 0
            for dy, dx in cells:
                mask |= 1 << (W * (y + dy) + x + dx)
            out.append((mask, x, y))
    return out


PLACEMENTS = [_placements(piece) for piece in PIECE_POOL]


def to_bits(grid):
    bits = 0
    for y, row in enumerate(grid):
        for x, cell in enumerate(row):
            if cell:
                bits |= 1 << (W * y + x)
    return bits


def clear_lines(bits):
    gone = 0
    for m in ROWS:
        if (bits & m) == m:
            gone |= m
    for m in COLS:
        if (bits & m) == m:
            gone |= m
    return bits & ~gone


def features(bits):
    empty = ~bits & FULL
    near = ((empty << 1) & NOT_COL0) | ((empty >> 1) & NOT_COL7) | (empty << W) | (empty >> W)
    iso = (empty & ~near).bit_count()
    fill = bits
    for _ in range(W - 1):
        fill |= fill << W
    holes = (empty & fill).bit_count()
    t3 = empty & ((empty >> 1) & LE6) & ((empty >> 2) & LE5)
    sq = (t3 & (t3 >> W) & (t3 >> 2 * W)).bit_count()
    return bits.bit_count(), iso, holes, sq


def _score(bits):
    occ, iso, holes, sq = features(bits)
    return -OCC_W * occ - ISO_W * iso - HOLE_W * holes + SQ_W * min(sq, SQ_CAP)


def playable(bits, poses, budget):
    if not poses:
        return True
    budget[0] -= 1
    if budget[0] < 0:
        return True
    for i, pose in enumerate(poses):
        rest = poses[:i] + poses[i + 1:]
        for mask, _, _ in PLACEMENTS[pose]:
            if not (bits & mask) and playable(clear_lines(bits | mask), rest, budget):
                return True
    return False


class SearchPolicy:
    name = "search"

    def __init__(self):
        self.reset(0)

    def reset(self, game_seed):
        self.rng = random.Random(f"search:{game_seed}")
        self.exhausted = 0

    def act(self, game, actions):
        bits = to_bits(game.board.grid)
        remaining = tuple(
            (idx, piece.index) for idx, piece in enumerate(game.pieces) if piece is not None
        )
        leaves = self._leaves(bits, remaining)
        leaves.sort(key=lambda leaf: leaf[0], reverse=True)
        trays = self._hard_trays()
        best_score, best_move = None, None
        for cheap, leaf_bits, move in leaves[:FINAL]:
            bad = 0
            for tray in trays:
                budget = [TRAY_BUDGET]
                if not playable(leaf_bits, tray, budget):
                    bad += 1
                if budget[0] < 0:
                    self.exhausted += 1
            score = cheap - HARD_PENALTY * bad / SAMPLES
            if best_score is None or score > best_score:
                best_score, best_move = score, move
        return best_move if best_move is not None else actions[0]

    def _hard_trays(self):
        return [
            tuple(self.rng.choice(PIECE_TYPES[self.rng.choice(HARD_TYPES)]) for _ in range(3))
            for _ in range(SAMPLES)
        ]

    def _leaves(self, bits, remaining):
        frontier = [(bits, remaining, None)]
        while True:
            children = []
            for b, rem, first in frontier:
                for k, (idx, pose) in enumerate(rem):
                    rest = rem[:k] + rem[k + 1:]
                    for mask, x, y in PLACEMENTS[pose]:
                        if not (b & mask):
                            nb = clear_lines(b | mask)
                            children.append((_score(nb), nb, rest, first or (idx, x, y)))
            if not children:
                return []
            if not children[0][2]:
                return [(score, nb, move) for score, nb, _, move in children]
            children.sort(key=lambda child: child[0], reverse=True)
            frontier = [(nb, rest, move) for _, nb, rest, move in children[:BEAM]]
