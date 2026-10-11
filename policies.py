"""
Polityki grające, których używa benchmark.

Wszystkie są deterministyczne przy zadanym seedzie partii — benchmark mierzy,
co polityka umie, a nie jak wypada w trakcie nauki (#8).
"""
import itertools
import math
import random

from pieces import PIECE_POOL, PIECE_TYPES
from scoring import FULL_CLEAR_BONUS, clear_points, placement_points


class RandomPolicy:
    """Jednostajnie po dostępnych ruchach. Dolna granica odniesienia."""

    name = "random"

    def __init__(self, seed=0):
        self._seed = seed

    def reset(self, game_seed):
        self.rng = random.Random(f"{self._seed}:{game_seed}")

    def act(self, game, actions):
        return self.rng.choice(actions)


class GreedyPolicy:
    """Maksymalizuje punkty z bieżącego postawienia (jeden pół-ruch w przód)."""

    name = "greedy"

    def reset(self, game_seed):
        pass

    def act(self, game, actions):
        best, best_gain = actions[0], None
        for action in actions:
            gain = _immediate_gain(game, action)
            if best_gain is None or gain > best_gain:
                best, best_gain = action, gain
        return best


class ModelPolicy:
    """Wytrenowana sieć w trybie deterministycznym (ε = 0)."""

    def __init__(self, agent, name):
        self.agent = agent
        self.name = name

    def reset(self, game_seed):
        pass

    def act(self, game, actions):
        grid, shapes, numeric, _ = self.agent.get_state(game)
        move = self.agent.get_action((grid, shapes, numeric), epsilon=0.0)
        return tuple(move)


N = 8
FULL = (1 << (N * N)) - 1
ROWS = [0xFF << (N * r) for r in range(N)]
COLS = [sum(1 << (c + N * r) for r in range(N)) for c in range(N)]
NOT_COL0 = FULL & ~COLS[0]
NOT_COL7 = FULL & ~COLS[N - 1]
NOT_ROW7 = FULL & ~ROWS[N - 1]
BORDER = ROWS[0] | ROWS[N - 1] | COLS[0] | COLS[N - 1]

HARD_TYPES = (3, 4, 6, 7, 10)
N_TYPES = len(PIECE_TYPES)
HARD_SHARE = (len(HARD_TYPES) / N_TYPES) ** 3
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


def _placements(piece):
    h, w = len(piece.shape), len(piece.shape[0])
    base = sum(1 << (r * N + c) for r, row in enumerate(piece.shape) for c, v in enumerate(row) if v)
    return [(base << (y * N + x), x, y, y + h, x + w) for y in range(N + 1 - h) for x in range(N + 1 - w)]


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
                b |= 1 << (y * N + x)
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
    near = ((e >> 1) & NOT_COL7) | ((e << 1) & NOT_COL0) | (e >> N) | ((e << N) & FULL)
    iso = _pc(e & ~near)
    border = _pc(e & BORDER)
    inner = _pc((b ^ (b >> 1)) & NOT_COL7) + _pc((b ^ (b >> N)) & NOT_ROW7)
    return -1.4 * _pc(b) - 0.75 * iso - 1.5 * inner - 2.0 * border + 4.2 * lines


def _fits(b, i):
    return any(not m & b for m, _x, _y, _y1, _x1 in PLACEMENTS[i])


def _tray_ok(b, tray):
    """Czy wszystkie klocki tacki (indeksy PIECE_POOL) da się ułożyć w jakiejkolwiek kolejności."""
    if not tray:
        return True
    for j, i in enumerate(tray):
        if i in tray[:j]:
            continue
        rest = tray[:j] + tray[j + 1:]
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
        alive = sum(1 for i in idxs if _fits(b, i))
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
    return TRAY_FAIL * miss_live ** 3 + 80.0 * miss_all + 12.3 * dead + TRAY_FAIL * HARD_SHARE * hard


def plan(board, slots, width, cap, partial=False):
    beam = [(board, 0, 0, None)]
    for _ in slots:
        children = {}
        for b, used, lines, first in beam:
            for k, (sid, pi) in enumerate(slots):
                bit = 1 << k
                if used & bit:
                    continue
                for m, x, y, y1, x1 in PLACEMENTS[pi]:
                    if m & b:
                        continue
                    nb, cl = _clear(b | m, y, y1, x, x1)
                    nl = lines + cl
                    # Liczba linii w kluczu: ta sama plansza z inną liczbą linii ma inną wartość w cheap.
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


def _next_states(b, poses):
    states = plan(b, list(enumerate(poses)), LOOK_BEAM, LOOK_BEAM)[:2]
    return sorted(((cheap(s[0], s[2]), s[0]) for s in states), key=lambda t: -t[0])


def _next_risked(pairs, triples):
    return sorted(((c - risk(b, triples), b) for c, b in pairs), key=lambda t: -t[0])


def _next_value(pairs, mixed):
    best = None
    for u, b in pairs:
        if best is not None and u <= best:
            break
        v = u - tail_penalty(b, mixed)
        if best is None or v > best:
            best = v
    return -TRAY_FAIL if best is None else best


def _top_value(pairs):
    return pairs[0][0] if pairs else -TRAY_FAIL


class SurvivalPolicy:
    name = "survival"

    def __init__(self):
        self.rng = random.Random(0)

    def reset(self, game_seed):
        self.rng = random.Random(f"beam:{game_seed}")

    def act(self, game, actions):
        slots = [(idx, p.index) for idx, p in enumerate(game.pieces) if p is not None]
        base = _to_bits(game.board.grid)
        finals = plan(base, slots, BEAM, BEAM_CAP, partial=True)
        if _pc(finals[0][1]) < len(slots):
            return max(finals, key=lambda s: cheap(s[0], s[2]))[3]

        triples = _hard_triples(self.rng)
        mixed = _mixed_trays(self.rng)
        scored = sorted(((cheap(s[0], s[2]), s) for s in finals), key=lambda t: -t[0])
        k = FINAL_K_TIGHT if N * N - _pc(base) <= TIGHT_FREE else FINAL_K
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
        trays = [self._draw_tray() for _ in range(LOOK_TRAYS)]
        for first, (value, b) in contenders:
            looks = [_next_states(b, poses) for poses in trays]
            if best_total is not None and value + sum(_top_value(l) for l in looks) / LOOK_TRAYS <= best_total:
                continue
            looks = [_next_risked(l, triples) for l in looks]
            if best_total is not None and value + sum(_top_value(l) for l in looks) / LOOK_TRAYS <= best_total:
                continue
            total = value + sum(_next_value(l, mixed) for l in looks) / LOOK_TRAYS
            if best_total is None or total > best_total:
                best_move, best_total = first, total
        return best_move

    def _draw_tray(self):
        return [self.rng.choice(PIECE_TYPES[self.rng.randrange(N_TYPES)]) for _ in range(3)]


def build(weights):
    return SurvivalPolicy()


def _immediate_gain(game, action):
    """Punkty, które da to postawienie — wg skalibrowanego wzoru, bez zmiany stanu gry."""
    idx, x, y = action
    piece = game.pieces[idx]
    board = game.board.copy()
    board.place_piece(piece, x, y)

    gain = placement_points(piece)
    rows, cols = board.check_full_lines()
    lines = len(rows) + len(cols)
    if lines > 0:
        gain += clear_points(game.combo + 1, lines)
        board.clear_lines(rows, cols)
        if not any(any(row) for row in board.grid):
            gain += FULL_CLEAR_BONUS
    return gain
