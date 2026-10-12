"""
Polityki grające, których używa benchmark.

Wszystkie są deterministyczne przy zadanym seedzie partii — benchmark mierzy,
co polityka umie, a nie jak wypada w trakcie nauki (#8).
"""
import random

import bitboard
from board import Board
from generator import Generator
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


LINE_WEIGHT = 4.0
TRANSITION_WEIGHT = 1.0
NOFIT_WEIGHT = 30.0
DEAD_WEIGHT = 2000.0
BEAM = 12
FINALISTS = 12
REVIEW = 3
DRAWS = 4
TRAY_FAIL = 400.0
TAIL_DRAWS = 64
TAIL_WEIGHT = 400.0

_NOT_RIGHT_COL = sum(1 << (bitboard.SIZE * y + x) for y in range(bitboard.SIZE) for x in range(bitboard.SIZE - 1))
_NOT_BOTTOM_ROW = (1 << (bitboard.SIZE * (bitboard.SIZE - 1))) - 1
_WALL_MASKS = (bitboard.COL_MASKS[0], bitboard.COL_MASKS[-1], bitboard.ROW_MASKS[0], bitboard.ROW_MASKS[-1])
_PLACEMENTS = {}


def build(weights):
    """Polityka nie używa wag; argument zostaje ze względu na kontrakt oceny."""
    return TraySearchPolicy()


class TraySearchPolicy:
    """Wiązka po klockach tacki; trzy najlepsze pierwsze ruchy przegląda następna tacka na wspólnych losowaniach."""

    def __init__(self):
        self.reset(0)

    def reset(self, game_seed):
        # Inne ziarna niż w generatorze gry, inaczej przegląd i ogon widziałyby prawdziwą następną tackę.
        self._draws = Generator(f"przeglad:{game_seed}")
        self._tail = Generator(f"ogon:{game_seed}")

    def act(self, game, actions):
        slots = [(idx, _placements(piece.shape)) for idx, piece in enumerate(game.pieces) if piece is not None]
        occupied = bitboard.occupancy(game.board.grid)
        complete = _search(occupied, slots)
        if not complete:
            return _survive_longest(slots, occupied)
        tails = [self._tail.next_pieces() for _ in range(TAIL_DRAWS)]
        heads = _heads(complete, tails)
        if len(heads) == 1:
            return heads[0][2]
        trays = [self._draws.next_pieces() for _ in range(DRAWS)]
        return max(heads, key=lambda h: h[0] + _review(h[1], trays))[2]


def _placements(shape):
    key = tuple(tuple(row) for row in shape)
    if key not in _PLACEMENTS:
        size = bitboard.SIZE
        cells = [(dx, dy) for dy, row in enumerate(shape) for dx, cell in enumerate(row) if cell]
        h, w = len(shape), len(shape[0])
        out = []
        for y in range(size - h + 1):
            for x in range(size - w + 1):
                mask = 0
                for dx, dy in cells:
                    mask |= 1 << (size * (y + dy) + x + dx)
                out.append((x, y, mask))
        _PLACEMENTS[key] = out
    return _PLACEMENTS[key]


def _transitions(bits):
    empty = bitboard.FULL ^ bits
    inner = ((bits ^ (bits >> 1)) & _NOT_RIGHT_COL).bit_count()
    inner += ((bits ^ (bits >> bitboard.SIZE)) & _NOT_BOTTOM_ROW).bit_count()
    walls = sum((empty & mask).bit_count() for mask in _WALL_MASKS)
    return inner + walls


def _value(clears, bits):
    return LINE_WEIGHT * clears - TRANSITION_WEIGHT * _transitions(bits)


def _risk(bits):
    p = 1.0 - bitboard.fit_stats(bitboard.fit_masks(bits))[0]
    return DEAD_WEIGHT * p ** 3 + NOFIT_WEIGHT * p


def _fits(bits, places):
    return any((bits & mask) == 0 for _, _, mask in places)


def _completable(bits, slots):
    if not slots:
        return True
    for j, places in enumerate(slots):
        rest = slots[:j] + slots[j + 1:]
        for _, _, mask in places:
            if bits & mask:
                continue
            child, _ = bitboard.clear_lines(bits | mask)
            if _completable(child, rest):
                return True
    return False


def _dead_share(bits, tails):
    if not tails:
        return 0.0
    dead = sum(not _completable(bits, [_placements(piece.shape) for piece in tray]) for tray in tails)
    return dead / len(tails)


def _search(start, slots):
    frontier = [(_value(0, start), 0, start, (1 << len(slots)) - 1, None)]
    complete = []
    while frontier:
        children = {}
        for _, clears, bits, rem, first in frontier:
            for j, (idx, places) in enumerate(slots):
                if not (rem >> j) & 1:
                    continue
                left = rem & ~(1 << j)
                for x, y, mask in places:
                    if bits & mask:
                        continue
                    nxt, lines = bitboard.clear_lines(bits | mask)
                    cl = clears + lines
                    val = _value(cl, nxt)
                    key = (nxt, left)
                    prev = children.get(key)
                    if prev is None or val > prev[0]:
                        children[key] = (val, cl, nxt, left, first or (idx, x, y))
        frontier = []
        for val, cl, nxt, left, move in sorted(children.values(), key=lambda s: s[0], reverse=True):
            if left == 0:
                complete.append((val, nxt, move))
            elif len(frontier) < BEAM and any(_fits(nxt, slots[k][1]) for k in range(len(slots)) if (left >> k) & 1):
                frontier.append((val, cl, nxt, left, move))
    return complete


def _ranked(complete, tails=()):
    finalists = sorted(complete, key=lambda s: s[0], reverse=True)[:FINALISTS]
    scored = ((s[0] - _risk(s[1]) - TAIL_WEIGHT * _dead_share(s[1], tails), s[1], s[2]) for s in finalists)
    return sorted(scored, key=lambda h: h[0], reverse=True)


def _heads(complete, tails=()):
    heads, seen = [], set()
    for head in _ranked(complete, tails):
        if head[2] in seen:
            continue
        seen.add(head[2])
        heads.append(head)
        if len(heads) == REVIEW:
            break
    return heads


def _review(board, trays):
    values = []
    for tray in trays:
        ranked = _ranked(_search(board, [(i, _placements(piece.shape)) for i, piece in enumerate(tray)]))
        if ranked:
            values.append(ranked[0][0])
    return sum(values) / len(values) if values else -TRAY_FAIL


def _survive_longest(slots, occupied):
    best_move, best_key = None, None
    for idx, places in slots:
        rest = [slot for slot in slots if slot[0] != idx]
        for x, y, mask in places:
            if occupied & mask:
                continue
            child, _ = bitboard.clear_lines(occupied | mask)
            fit, _ = bitboard.fit_stats(bitboard.fit_masks(child))
            key = (1 + _max_placements(child, rest), fit)
            if best_key is None or key > best_key:
                best_move, best_key = (idx, x, y), key
    return best_move


def _max_placements(occupied, slots):
    best = 0
    for j, (_, places) in enumerate(slots):
        rest = slots[:j] + slots[j + 1:]
        for _, _, mask in places:
            if occupied & mask:
                continue
            child, _ = bitboard.clear_lines(occupied | mask)
            best = max(best, 1 + _max_placements(child, rest))
            if best == len(slots):
                return best
    return best
