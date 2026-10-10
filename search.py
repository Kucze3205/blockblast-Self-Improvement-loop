import random

from bitboard import COL_MASK, FULL, POSES, ROW_MASK, W, bits, clear_full, fit, place, to_mask
from pieces import PIECE_TYPES

BEAM = 40
FINAL = 12
DRAWS = 3
HARD_TYPES = (4, 6, 7, 10, 9)
HARD_PENALTY = 500.0
LINE_W = 4.2
OCC_W = 1.4
ISO_W = 0.75
TRANS_W = 1.5
EDGE_W = 2.0
FIT_CUBE_W = 400.0
FIT_MEAN_W = 80.0
DEAD_W = 12.3

NOT_COL0 = FULL & ~COL_MASK[0]
NOT_COL7 = FULL & ~COL_MASK[W - 1]
NOT_ROW7 = FULL & ~ROW_MASK[W - 1]
RING = ROW_MASK[0] | ROW_MASK[W - 1] | COL_MASK[0] | COL_MASK[W - 1]


def _count(mask):
    return bin(mask).count("1")


def _cheap(occ, lines):
    left = (occ << 1) & NOT_COL0
    right = (occ >> 1) & NOT_COL7
    up = (occ << W) & FULL
    down = occ >> W
    pockets = ((left & right & up) | (left & right & down) | (left & up & down) | (right & up & down)) & ~occ
    trans = _count((occ ^ (occ >> 1)) & NOT_COL7) + _count((occ ^ (occ >> W)) & NOT_ROW7)
    return (
        LINE_W * lines
        - OCC_W * _count(occ)
        - ISO_W * _count(pockets)
        - TRANS_W * trans
        - EDGE_W * _count(RING & ~occ)
    )


def _seq(rest, occ):
    if not rest:
        return True
    free = FULL & ~occ
    for i, pose in enumerate(rest):
        others = rest[:i] + rest[i + 1:]
        for anchor in bits(fit(pose, free)):
            occ2, _ = clear_full(place(occ, pose, anchor))
            if _seq(others, occ2):
                return True
    return False


def _slots(types, draws):
    seen = {}
    out = []
    for t in types:
        s = seen.get(t, 0)
        seen[t] = s + 1
        out.append(draws[t][s])
    return out


def _risk(occ, draws):
    k = len(HARD_TYPES)
    bad = 0
    for a in range(k):
        for b in range(a, k):
            for c in range(b, k):
                if not _seq(_slots((HARD_TYPES[a], HARD_TYPES[b], HARD_TYPES[c]), draws), occ):
                    bad += 1 if a == b == c else (3 if a == b or b == c else 6)
    return bad / k ** 3


def _fit_penalty(occ):
    free = FULL & ~occ
    shares = [sum(1 for p in poses if fit(POSES[p], free)) / len(poses) for poses in PIECE_TYPES]
    dead = sum(1 for share in shares if share == 0)
    alive = [share for share in shares if share > 0]
    mean_alive = sum(alive) / len(alive) if alive else 0.0
    mean_all = sum(shares) / len(shares)
    return FIT_CUBE_W * (1 - mean_alive) ** 3 + FIT_MEAN_W * (1 - mean_all) + DEAD_W * dead


def _penalty(occ, draws):
    return -(_fit_penalty(occ) + HARD_PENALTY * _risk(occ, draws))


def plan_tray(occ, pieces, rng):
    """pieces: [(indeks w game.pieces, Pose)]. Zwraca [(indeks, anchor)] albo []."""
    draws = {t: [POSES[rng.choice(PIECE_TYPES[t])] for _ in range(DRAWS)] for t in HARD_TYPES}
    states = [(0.0, occ, tuple(range(len(pieces))), (), 0)]
    for _ in pieces:
        children = []
        for _value, occ_s, rem, seq, lines_s in states:
            free = FULL & ~occ_s
            for j in rem:
                game_index, pose = pieces[j]
                rest = tuple(k for k in rem if k != j)
                for anchor in bits(fit(pose, free)):
                    occ2, lines = clear_full(place(occ_s, pose, anchor))
                    lines_total = lines_s + lines
                    children.append((_cheap(occ2, lines_total), occ2, rest, seq + ((game_index, anchor),), lines_total))
        if not children:
            break
        children.sort(key=lambda c: c[0], reverse=True)
        states = children[:BEAM]
    if not states or not states[0][3]:
        return []
    best = max(states[:FINAL], key=lambda s: s[0] + _penalty(s[1], draws))
    return list(best[3])


class SearchPolicy:
    name = "search"

    def __init__(self):
        self.reset(0)

    def reset(self, game_seed):
        self._plan = []
        self._rng = random.Random(f"search:{game_seed}")

    def act(self, game, actions):
        legal = set(actions)
        if self._plan and self._plan[0] in legal:
            return self._plan.pop(0)
        pieces = [(i, POSES[p.index]) for i, p in enumerate(game.pieces) if p is not None]
        self._plan = [(gi, a % W, a // W) for gi, a in plan_tray(to_mask(game.board.grid), pieces, self._rng)]
        if self._plan and self._plan[0] in legal:
            return self._plan.pop(0)
        return actions[0]
