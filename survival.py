"""
Polityka przeżycia: wiązka po klockach bieżącej tacki i ryzyko trudnych tacek.

Cechy liścia z lokalnego strojenia (drzewo 5, węzeł 2.1), ryzyko trudnych tacek
ważone multizbiorem (5/4.2) z osobną pozą dla każdego miejsca w tacce (5/4.3).
Czysty Python na bitboardach; bez numpy i torch.
"""
import math
import random

from bitboard import BORDER, FULL, NOT_COL0, NOT_COL7, POSES, fit_mask, line_clear
from pieces import PIECE_TYPES

BEAM = 40
FINAL_SMALL = 8
FINAL_LARGE = 20
FINAL_FREE_CELLS = 22
W_OCC = 1.4
W_ISO = 0.75
W_EDGE = 1.5
W_BORDER = 2.0
W_LINE = 4.2
W_FIT = 400.0
W_FIT_LIN = 80.0
W_DEAD = 12.3
W_HARD = 400.0
HARD_TYPES = (3, 4, 7, 6, 10)


def _hard_multisets():
    n = len(HARD_TYPES)
    out = []
    for i in range(n):
        for j in range(i, n):
            for k in range(j, n):
                trio = (HARD_TYPES[i], HARD_TYPES[j], HARD_TYPES[k])
                seen = {}
                slots = []
                for t in trio:
                    slots.append((t, seen.get(t, 0)))
                    seen[t] = seen.get(t, 0) + 1
                perms = math.factorial(3)
                for count in seen.values():
                    perms //= math.factorial(count)
                out.append((perms / n ** 3, tuple(slots)))
    return out


HARD_MULTISETS = _hard_multisets()


def _occupancy(grid):
    occ = 0
    for y, row in enumerate(grid):
        for x, cell in enumerate(row):
            if cell:
                occ |= 1 << (y * 8 + x)
    return occ


def _cheap(occ):
    free = FULL & ~occ
    nb = (free >> 8) | (free << 8) | ((free >> 1) & NOT_COL7) | ((free << 1) & NOT_COL0)
    iso = (free & ~nb).bit_count()
    edges = ((occ ^ (occ >> 1)) & NOT_COL7).bit_count() + ((occ ^ (occ >> 8)) & (FULL >> 8)).bit_count()
    border = (free & BORDER).bit_count()
    return -(W_OCC * occ.bit_count() + W_ISO * iso + W_EDGE * edges + W_BORDER * border)


def _search(occ, pieces):
    """Wiązka po kolejnościach i pozycjach klocków tacki; zwraca (stany, czy pełne)."""
    beam = [(0.0, occ, 0, 0, None)]
    for _ in pieces:
        children = {}
        for _score, board, lines, used, first in beam:
            for j, (_idx, pose) in enumerate(pieces):
                bit = 1 << j
                if used & bit:
                    continue
                m = fit_mask(board, pose)
                while m:
                    low = m & -m
                    nxt, cleared = line_clear(board | pose.base * low)
                    nlines = lines + cleared
                    key = (nxt, used | bit)
                    score = _cheap(nxt) + W_LINE * nlines
                    old = children.get(key)
                    if old is None or score > old[0]:
                        children[key] = (score, nxt, nlines, used | bit, first or (j, low))
                    m ^= low
        if not children:
            break
        beam = sorted(children.values(), key=lambda s: -s[0])[:BEAM]
    return beam, bool(beam) and beam[0][3].bit_count() == len(pieces)


def _tray_ok(occ, poses):
    if not poses:
        return True
    for i, pose in enumerate(poses):
        rest = poses[:i] + poses[i + 1:]
        m = fit_mask(occ, pose)
        while m:
            low = m & -m
            nxt, _ = line_clear(occ | pose.base * low)
            if _tray_ok(nxt, rest):
                return True
            m ^= low
    return False


def _type_stats(occ):
    total = 0.0
    dead = 0
    for poses in PIECE_TYPES:
        fits = sum(1 for p in poses if fit_mask(occ, POSES[p]))
        total += fits / len(poses)
        dead += fits == 0
    return total / len(PIECE_TYPES), dead


def _risk(occ, sampled):
    avg, dead = _type_stats(occ)
    miss = 1.0 - avg
    hard = 0.0
    for weight, slots in HARD_MULTISETS:
        if not _tray_ok(occ, [POSES[sampled[t][j]] for t, j in slots]):
            hard += weight
    return W_FIT * miss ** 3 + W_FIT_LIN * miss + W_DEAD * dead + W_HARD * hard


class SurvivalPolicy:
    name = "survival"

    def __init__(self, seed=0):
        self._seed = seed
        self.rng = random.Random(f"{seed}:0")

    def reset(self, game_seed):
        self.rng = random.Random(f"{self._seed}:{game_seed}")

    def act(self, game, actions):
        occ = _occupancy(game.board.grid)
        pieces = [(idx, POSES[p.index]) for idx, p in enumerate(game.pieces) if p is not None]
        sampled = {t: [self.rng.choice(PIECE_TYPES[t]) for _ in range(3)] for t in HARD_TYPES}
        beam, complete = _search(occ, pieces)
        if not complete:
            _score, _board, _lines, _used, (j, low) = max(beam, key=lambda s: s[0])
        else:
            final = FINAL_LARGE if (FULL & ~occ).bit_count() <= FINAL_FREE_CELLS else FINAL_SMALL
            best = None
            for score, board, _lines, _used, first in beam[:final]:
                value = score - _risk(board, sampled)
                if best is None or value > best[0]:
                    best = (value, first)
            j, low = best[1]
        idx = pieces[j][0]
        anchor = low.bit_length() - 1
        return (idx, anchor % 8, anchor // 8)
