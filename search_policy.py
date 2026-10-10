"""Wiązka po klockach tacki na bitboardach z karą za trudne tacki."""
import itertools
import random

from pieces import PIECE_POOL, PIECE_TYPES

W = 8
FULL = (1 << (W * W)) - 1
ROWS = [0xFF << (W * y) for y in range(W)]
COLS = [sum(1 << (W * y + x) for y in range(W)) for x in range(W)]
NOT_COL0 = FULL & ~COLS[0]
NOT_COL7 = FULL & ~COLS[W - 1]
NOT_ROW7 = FULL & ~ROWS[W - 1]
RING = ROWS[0] | ROWS[W - 1] | COLS[0] | COLS[W - 1]

HARD_TYPES = (3, 4, 7, 6, 10)  # beam4, beam5, square3, rect23, corner5
BEAM = 40
FINAL = 12
TRAY_BUDGET = 400
MIX_SAMPLES = 24
HARD_MULTISETS = [
    (types, len(set(itertools.permutations(types))) / len(HARD_TYPES) ** 3)
    for types in itertools.combinations_with_replacement(HARD_TYPES, 3)
]
DEFAULT_WEIGHTS = {
    "OCC_W": 1.4,
    "ISO_W": 0.75,
    "TRANS_W": 1.5,
    "EDGE_W": 2.0,
    "LINE_REWARD": 4.2,
    "FIT_CUBE_W": 400.0,
    "FIT_MEAN_W": 80.0,
    "DEAD_W": 12.3,
    "HARD_PENALTY": 400.0,
    "MIX_PENALTY": 100.0,
}


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
    cleared = 0
    for m in ROWS:
        if (bits & m) == m:
            gone |= m
            cleared += 1
    for m in COLS:
        if (bits & m) == m:
            gone |= m
            cleared += 1
    return bits & ~gone, cleared


def features(bits):
    left = (bits << 1) & NOT_COL0
    right = (bits >> 1) & NOT_COL7
    up = (bits << W) & FULL
    down = bits >> W
    pockets = (left & right & up) | (left & right & down) | (left & up & down) | (right & up & down)
    trans = ((bits ^ (bits >> 1)) & NOT_COL7).bit_count() + ((bits ^ (bits >> W)) & NOT_ROW7).bit_count()
    return bits.bit_count(), (pockets & ~bits).bit_count(), trans, (RING & ~bits).bit_count()


def _cheap(bits, lines, w):
    occ, iso, trans, edge = features(bits)
    return (
        w["LINE_REWARD"] * lines
        - w["OCC_W"] * occ
        - w["ISO_W"] * iso
        - w["TRANS_W"] * trans
        - w["EDGE_W"] * edge
    )


def _fit_penalty(bits, w):
    shares = []
    dead = 0
    for poses in PIECE_TYPES:
        fitting = sum(1 for pose in poses if any(not (bits & mask) for mask, _, _ in PLACEMENTS[pose]))
        shares.append(fitting / len(poses))
        if fitting == 0:
            dead += 1
    mean_all = sum(shares) / len(shares)
    alive = [share for share in shares if share > 0]
    mean_alive = sum(alive) / len(alive) if alive else 0.0
    return (
        w["FIT_CUBE_W"] * (1 - mean_alive) ** 3
        + w["FIT_MEAN_W"] * (1 - mean_all)
        + w["DEAD_W"] * dead
    )


def playable(bits, poses, budget):
    if not poses:
        return True
    budget[0] -= 1
    if budget[0] < 0:
        return True
    for i, pose in enumerate(poses):
        rest = poses[:i] + poses[i + 1:]
        for mask, _, _ in PLACEMENTS[pose]:
            if not (bits & mask):
                nxt, _ = clear_lines(bits | mask)
                if playable(nxt, rest, budget):
                    return True
    return False


class SearchPolicy:
    name = "search"

    def __init__(self, weights=None):
        self.w = {**DEFAULT_WEIGHTS, **(weights or {})}
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
        mixed = self._mixed_trays()
        best_score, best_move = None, None
        for cheap, leaf_bits, moves in leaves[:FINAL]:
            risk = self._risk(leaf_bits, trays)
            mix_risk = self._risk(leaf_bits, mixed)
            score = (
                cheap
                - _fit_penalty(leaf_bits, self.w)
                - self.w["HARD_PENALTY"] * risk
                - self.w["MIX_PENALTY"] * mix_risk
            )
            if best_score is None or score > best_score:
                best_score, best_move = score, min(moves)
        return best_move if best_move is not None else actions[0]

    def _risk(self, bits, trays):
        risk = 0.0
        for weight, tray in trays:
            budget = [TRAY_BUDGET]
            if not playable(bits, tray, budget):
                risk += weight
            if budget[0] < 0:
                self.exhausted += 1
        return risk

    def _hard_trays(self):
        draws = {t: [self.rng.choice(PIECE_TYPES[t]) for _ in range(3)] for t in HARD_TYPES}
        trays = []
        for types, weight in HARD_MULTISETS:
            used = {}
            tray = []
            for t in types:
                k = used.get(t, 0)
                used[t] = k + 1
                tray.append(draws[t][k])
            trays.append((weight, tuple(tray)))
        return trays

    def _mixed_trays(self):
        trays = []
        while len(trays) < MIX_SAMPLES:
            types = [self.rng.randrange(len(PIECE_TYPES)) for _ in range(3)]
            hard = sum(t in HARD_TYPES for t in types)
            if hard in (0, 3):
                continue
            trays.append(tuple(self.rng.choice(PIECE_TYPES[t]) for t in types))
        return [(1 / MIX_SAMPLES, tray) for tray in trays]

    def _leaves(self, bits, remaining):
        frontier = [(bits, remaining, frozenset(), 0)]
        while True:
            children = {}
            for b, rem, moves, lines in frontier:
                for k, (idx, pose) in enumerate(rem):
                    rest = rem[:k] + rem[k + 1:]
                    for mask, x, y in PLACEMENTS[pose]:
                        if not (b & mask):
                            nb, cleared = clear_lines(b | mask)
                            total = lines + cleared
                            key = (nb, tuple(sorted(p for _, p in rest)), total)
                            first = moves or frozenset({(idx, x, y)})
                            if key in children:
                                children[key][4].update(first)
                            else:
                                children[key] = [_cheap(nb, total, self.w), nb, rest, total, set(first)]
            if not children:
                return []
            if len(frontier[0][1]) == 1:
                return [(score, nb, moves) for score, nb, _, _, moves in children.values()]
            ranked = sorted(children.values(), key=lambda child: child[0], reverse=True)
            frontier = [(nb, rest, moves, total) for _, nb, rest, total, moves in ranked[:BEAM]]
