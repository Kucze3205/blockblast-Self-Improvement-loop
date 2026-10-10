import random

from bitboard import COL_MASK, FULL, POSES, ROW_MASK, W, bits, clear_full, fit, place, to_mask
from pieces import PIECE_TYPES

BEAM = 40
FINAL = 8
FINAL_CROWDED = 20
CROWDED_FREE = 22
LINE_W = 4.2
OCC_W = 1.4
POCKET_W = 0.75
DEAD_W = 12.3
FIT_W = 400.0
FIT_LIN_W = 80.0
HARD_K = 5
HARD_W = 400.0
DRAWS = 3
TYPE_COUNT = len(PIECE_TYPES)

NOT_COL0 = FULL & ~COL_MASK[0]
NOT_COL7 = FULL & ~COL_MASK[W - 1]
ROW0 = ROW_MASK[0]
ROWN = ROW_MASK[-1]


def _pockets(occ):
    blocked_up = ((occ << W) & FULL) | ROW0
    blocked_down = (occ >> W) | ROWN
    blocked_left = ((occ << 1) & NOT_COL0) | COL_MASK[0]
    blocked_right = ((occ >> 1) & NOT_COL7) | COL_MASK[W - 1]
    u, d, l, r = blocked_up, blocked_down, blocked_left, blocked_right
    three = (u & d & l) | (u & d & r) | (u & l & r) | (d & l & r)
    return FULL & ~occ & three


# zajętość liczona z resztą tacki: stany z różnymi klockami są wtedy porównywalne
def _cheap(occ, lines, rest_cells):
    return LINE_W * lines - OCC_W * (bin(occ).count("1") + rest_cells) - POCKET_W * bin(_pockets(occ)).count("1")


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


def _risk(occ, hard, alive, uniforms):
    k = len(hard)
    if not k:
        return 0.0
    draws = {t: [alive[t][int(uniforms[t][s] * len(alive[t]))] for s in range(DRAWS)] for t in hard}
    bad = 0
    for a in range(k):
        for b in range(a, k):
            for c in range(b, k):
                if not _seq(_slots((hard[a], hard[b], hard[c]), draws), occ):
                    bad += 1 if a == b == c else (3 if a == b or b == c else 6)
    return bad / k ** 3


def _penalty(occ, uniforms):
    free = FULL & ~occ
    dead = 0
    alive = [[] for _ in range(TYPE_COUNT)]
    for pose in POSES:
        if fit(pose, free):
            alive[pose.type_index].append(pose)
        else:
            dead += 1
    frac = [len(alive[t]) / len(PIECE_TYPES[t]) for t in range(TYPE_COUNT)]
    miss = 1.0 - sum(frac) / TYPE_COUNT
    hard = sorted((t for t in range(TYPE_COUNT) if alive[t]), key=lambda t: (frac[t], t))[:HARD_K]
    risk = _risk(occ, hard, alive, uniforms)
    return -(DEAD_W * dead + FIT_W * miss ** 3 + FIT_LIN_W * miss + HARD_W * risk)


def plan_tray(occ, pieces, rng):
    """pieces: [(indeks w game.pieces, Pose)]. Zwraca [(indeks, anchor)] albo []."""
    uniforms = [[rng.random() for _ in range(DRAWS)] for _ in range(TYPE_COUNT)]
    sizes = [len(pose.offsets) for _, pose in pieces]
    states = [(0.0, occ, tuple(range(len(pieces))), (), 0)]
    for _ in pieces:
        children = []
        for _value, occ_s, rem, seq, lines_s in states:
            free = FULL & ~occ_s
            for j in rem:
                game_index, pose = pieces[j]
                rest = tuple(k for k in rem if k != j)
                rest_cells = sum(sizes[k] for k in rest)
                for anchor in bits(fit(pose, free)):
                    occ2, lines = clear_full(place(occ_s, pose, anchor))
                    lines_total = lines_s + lines
                    children.append(
                        (_cheap(occ2, lines_total, rest_cells), occ2, rest, seq + ((game_index, anchor),), lines_total)
                    )
        if not children:
            break
        children.sort(key=lambda c: c[0], reverse=True)
        states = children[:BEAM]
    if not states or not states[0][3]:
        return []
    free_cells = bin(FULL & ~occ).count("1")
    finals = FINAL_CROWDED if free_cells <= CROWDED_FREE else FINAL
    best = max(states[:finals], key=lambda s: s[0] + _penalty(s[1], uniforms))
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
