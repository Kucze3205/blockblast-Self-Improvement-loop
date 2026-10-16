"""Wiązka po tacce na bitboardach: plan ułożenia tacki, ocena liścia, przegląd następnej tacki."""
import itertools
import math
import random

from pieces import PIECE_POOL, PIECE_TYPES

FULL = (1 << 64) - 1
ROWS = [0xFF << (8 * r) for r in range(8)]
COLS = [sum(1 << (c + 8 * r) for r in range(8)) for c in range(8)]
NOT_COL0 = FULL & ~COLS[0]
NOT_COL7 = FULL & ~COLS[7]
NOT_ROW7 = FULL & ~ROWS[7]
BORDER = ROWS[0] | ROWS[7] | COLS[0] | COLS[7]

HARD_TYPES = (3, 4, 6, 7, 10)
N_TYPES = len(PIECE_TYPES)
BEAM = 120
BEAM_CAP = 160
LOOK_BEAM = 40
LOOK_TRAYS = 4
LOOK_TOP = 3
FINAL_K = 8
FINAL_K_TIGHT = 20
TIGHT_FREE = 22
TRAY_FAIL = 400.0
MIX_TRAYS = 64
# P(trzy klocki z HARD_TYPES); wagi _hard_triples są warunkowe na taką tackę
P_HARD = (len(HARD_TYPES) / N_TYPES) ** 3


def _placements(piece):
    h, w = len(piece.shape), len(piece.shape[0])
    base = sum(1 << (r * 8 + c) for r, row in enumerate(piece.shape) for c, v in enumerate(row) if v)
    return [(base << (y * 8 + x), x, y, y + h, x + w) for y in range(9 - h) for x in range(9 - w)]


PLACEMENTS = [_placements(p) for p in PIECE_POOL]

HARD_TRIPLES = []
for _combo in itertools.combinations_with_replacement(HARD_TYPES, 3):
    _perms = 6
    for _t in set(_combo):
        _perms //= math.factorial(_combo.count(_t))
    HARD_TRIPLES.append((_perms / 125.0, _combo))


_pc = int.bit_count


def _to_bits(grid):
    b = 0
    for y, row in enumerate(grid):
        for x, cell in enumerate(row):
            if cell:
                b |= 1 << (y * 8 + x)
    return b


def _clear(b, y0, y1, x0, x1):
    kill = 0
    lines = 0
    for r in range(y0, y1):
        if (b & ROWS[r]) == ROWS[r]:
            kill |= ROWS[r]
            lines += 1
    for c in range(x0, x1):
        if (b & COLS[c]) == COLS[c]:
            kill |= COLS[c]
            lines += 1
    return (b & ~kill) if kill else b, lines


def cheap(b, lines):
    e = FULL & ~b
    near = ((e >> 1) & NOT_COL7) | ((e << 1) & NOT_COL0) | (e >> 8) | ((e << 8) & FULL)
    iso = _pc(e & ~near)
    border = _pc(e & BORDER)
    inner = _pc((b ^ (b >> 1)) & NOT_COL7) + _pc((b ^ (b >> 8)) & NOT_ROW7)
    return -1.4 * _pc(b) - 0.75 * iso - 1.5 * inner - 2.0 * border + 4.2 * lines


def _fits(b, i):
    for m, _x, _y, _y1, _x1 in PLACEMENTS[i]:
        if not m & b:
            return True
    return False


def _tray_ok(b, poses):
    if not poses:
        return True
    for j, i in enumerate(poses):
        if i in poses[:j]:
            continue
        rest = poses[:j] + poses[j + 1:]
        for m, x, y, y1, x1 in PLACEMENTS[i]:
            if not m & b:
                nb, _ = _clear(b | m, y, y1, x, x1)
                if _tray_ok(nb, rest):
                    return True
    return False


def _sample_tray(rng):
    return [rng.choice(rng.choice(PIECE_TYPES)) for _ in range(3)]


def _hard_triples(rng):
    draws = {t: [rng.choice(PIECE_TYPES[t]) for _ in range(3)] for t in HARD_TYPES}
    triples = []
    for w, combo in HARD_TRIPLES:
        used = {}
        poses = []
        for t in combo:
            k = used.get(t, 0)
            used[t] = k + 1
            poses.append(draws[t][k])
        triples.append((w, tuple(poses)))
    return triples


def _mixed_trays(rng):
    trays = [_sample_tray(rng) for _ in range(MIX_TRAYS)]
    return [t for t in trays if any(PIECE_POOL[i].type_index not in HARD_TYPES for i in t)]


def tail_penalty(b, trays):
    if not trays:
        return 0.0
    return TRAY_FAIL * sum(1 for t in trays if not _tray_ok(b, t)) / len(trays)


def risk(b, triples):
    shares = []
    dead = 0
    for idxs in PIECE_TYPES:
        alive = 0
        for i in idxs:
            if _fits(b, i):
                alive += 1
        shares.append(alive / len(idxs))
        if alive == 0:
            dead += 1
    live = [s for s in shares if s > 0]
    mean_live = sum(live) / len(live) if live else 0.0
    mean_all = sum(shares) / N_TYPES
    hard = 0.0
    for w, poses in triples:
        if not _tray_ok(b, poses):
            hard += w
    miss_live = 1.0 - mean_live
    miss_all = 1.0 - mean_all
    return TRAY_FAIL * miss_live ** 3 + 80.0 * miss_all + 12.3 * dead + TRAY_FAIL * P_HARD * hard


def plan(board, slots, width, cap, partial=False):
    beam = [(board, 0, 0, None)]
    for _ in slots:
        children = {}
        for b, used, lines, first in beam:
            for k, (sid, pls) in enumerate(slots):
                bit = 1 << k
                if used & bit:
                    continue
                for m, x, y, y1, x1 in pls:
                    if m & b:
                        continue
                    nb, cl = _clear(b | m, y, y1, x, x1)
                    nl = lines + cl
                    # linie w kluczu: ta sama plansza z inną liczbą linii ma inną wartość w cheap
                    key = (nb, used | bit, nl)
                    if key not in children:
                        children[key] = (nb, used | bit, nl, first or (sid, x, y))
        if not children:
            return beam if partial else []
        scored = sorted(((cheap(s[0], s[2]), s) for s in children.values()), key=lambda t: -t[0])
        if len(scored) > width:
            cut = scored[width - 1][0]
            keep = width
            while keep < min(cap, len(scored)) and scored[keep][0] == cut:
                keep += 1
            scored = scored[:keep]
        beam = [s for _, s in scored]
    return beam


class BeamPolicy:
    name = "beam"

    def __init__(self):
        self.rng = random.Random(0)

    def reset(self, game_seed):
        self.rng = random.Random(f"beam:{game_seed}")

    def act(self, game, actions):
        slots = [(idx, _placements(p)) for idx, p in enumerate(game.pieces) if p is not None]
        base = _to_bits(game.board.grid)
        finals = plan(base, slots, BEAM, BEAM_CAP, partial=True)
        if _pc(finals[0][1]) < len(slots):
            return max(finals, key=lambda s: cheap(s[0], s[2]))[3]

        triples = _hard_triples(self.rng)
        mixed = _mixed_trays(self.rng)
        scored = sorted(((cheap(s[0], s[2]), s) for s in finals), key=lambda t: -t[0])
        k = FINAL_K_TIGHT if 64 - _pc(base) <= TIGHT_FREE else FINAL_K
        cut = scored[min(k, len(scored)) - 1][0]
        best_by_move = {}
        for score, (b, _used, _lines, first) in scored:
            if score < cut:
                break
            value = score - risk(b, triples) - tail_penalty(b, mixed)
            if first not in best_by_move or value > best_by_move[first][0]:
                best_by_move[first] = (value, b)

        contenders = sorted(best_by_move.items(), key=lambda kv: -kv[1][0])[:LOOK_TOP]
        best_move, best_total = None, None
        trays = [_sample_tray(self.rng) for _ in range(LOOK_TRAYS)]
        for first, (value, b) in contenders:
            # śmierć na następnej tacce karze już risk i tail_penalty, więc tu liczymy tylko wykonalne
            nxt = [v for v in (self._next_value(b, triples, poses) for poses in trays) if v is not None]
            total = value + (sum(nxt) / len(nxt) if nxt else -TRAY_FAIL)
            if best_total is None or total > best_total:
                best_move, best_total = first, total
        return best_move

    def _next_value(self, b, triples, poses):
        states = plan(b, [(k, PLACEMENTS[i]) for k, i in enumerate(poses)], LOOK_BEAM, LOOK_BEAM)
        if not states:
            return None
        return max(cheap(s[0], s[2]) - risk(s[0], triples) for s in states[:2])
