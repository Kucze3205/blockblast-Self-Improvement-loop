"""
Polityki grające, których używa benchmark.

Wszystkie są deterministyczne przy zadanym seedzie partii — benchmark mierzy,
co polityka umie, a nie jak wypada w trakcie nauki (#8).
"""
import random

from board import Board
from pieces import CANONICAL_TYPES, PIECE_POOL, PIECE_TYPES
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


BEAM = 120
REVIEW = 8
MIXED_DRAWS = 64
HARD_DRAWS = 64
HARD_TYPE_NAMES = ("square3", "rect23", "beam5", "corner5", "beam4")
HARD_TYPES = [t for t, (name, _) in enumerate(CANONICAL_TYPES) if name in HARD_TYPE_NAMES]
ALL_TYPES = list(range(len(PIECE_TYPES)))
P_HARD = (len(HARD_TYPES) / len(PIECE_TYPES)) ** 3
DEATH = 400
RISK_CUBE = 400
RISK_MEAN = 80
RISK_DEAD_TYPE = 12.3
FULL = (1 << 64) - 1
ROWS = [0xFF << (8 * r) for r in range(8)]
COLS = [sum(1 << (8 * r + c) for r in range(8)) for c in range(8)]
NOT_COL0 = FULL ^ COLS[0]
NOT_COL7 = FULL ^ COLS[7]
NOT_ROW7 = FULL ^ ROWS[7]
BORDER = ROWS[0] | ROWS[7] | COLS[0] | COLS[7]


def _pose_table():
    table = []
    for piece in PIECE_POOL:
        h, w = len(piece.shape), len(piece.shape[0])
        cells = [(dx, dy) for dy, row in enumerate(piece.shape) for dx, cell in enumerate(row) if cell]
        origin = sum(1 << (dy * 8 + dx) for dx, dy in cells)
        anchors = sum(1 << (y * 8 + x) for y in range(9 - h) for x in range(9 - w))
        table.append((origin, anchors, [dy * 8 + dx for dx, dy in cells]))
    return table


POSES = _pose_table()


def _fit(pose, free):
    _, mask, shifts = pose
    for s in shifts:
        mask &= free >> s
    return mask


def _clear(occ):
    mask, lines = 0, 0
    for row in ROWS:
        if (occ & row) == row:
            mask |= row
            lines += 1
    for col in COLS:
        if (occ & col) == col:
            mask |= col
            lines += 1
    return occ & ~mask, lines


def _isolated(occ):
    empty = FULL & ~occ
    touch = ((empty << 1) & NOT_COL0) | ((empty >> 1) & NOT_COL7) | (empty << 8) | (empty >> 8)
    return bin(empty & ~touch).count("1")


def _transitions(occ):
    return bin((occ ^ (occ >> 1)) & NOT_COL7).count("1") + bin((occ ^ (occ >> 8)) & NOT_ROW7).count("1")


def _value(occ, lines):
    empty = FULL & ~occ
    return (
        4.2 * lines
        - 1.4 * bin(occ).count("1")
        - 0.75 * _isolated(occ)
        - 1.5 * _transitions(occ)
        - 2.0 * bin(empty & BORDER).count("1")
    )


def _tray_finals(occ, slots, width=BEAM):
    beam = [(occ, 0, None, tuple(slots))]
    for _ in slots:
        children = []
        for board, lines, first, left in beam:
            free = FULL & ~board
            for k, (slot, pose) in enumerate(left):
                rest = left[:k] + left[k + 1:]
                mask = _fit(pose, free)
                while mask:
                    low = mask & -mask
                    mask ^= low
                    anchor = low.bit_length() - 1
                    nxt, cleared = _clear(board | (pose[0] << anchor))
                    move = first or (slot, anchor % 8, anchor // 8)
                    total = lines + cleared
                    free2 = FULL & ~nxt
                    fits = sum(1 for _, p in rest if _fit(p, free2))
                    children.append(((fits, _value(nxt, total)), nxt, total, move, rest))
        if not children:
            break
        children.sort(key=lambda c: c[0], reverse=True)
        beam = [c[1:] for c in children[:width]]
    finals, seen = [], set()
    for board, lines, move, _ in beam:
        if move in seen:
            continue
        seen.add(move)
        finals.append((_value(board, lines), move, board))
        if len(finals) == REVIEW:
            break
    return finals


def _completable(occ, slots):
    if not slots:
        return True
    free = FULL & ~occ
    for i, pose in enumerate(slots):
        mask = _fit(pose, free)
        rest = slots[:i] + slots[i + 1:]
        while mask:
            low = mask & -mask
            mask ^= low
            nxt, _ = _clear(occ | (pose[0] << (low.bit_length() - 1)))
            if _completable(nxt, rest):
                return True
    return False


def _risk(occ):
    free = FULL & ~occ
    shares = [sum(1 for p in poses if _fit(POSES[p], free)) / len(poses) for poses in PIECE_TYPES]
    alive = [s for s in shares if s]
    cube = (1 - sum(alive) / len(alive)) ** 3 if alive else 1.0
    dead = len(shares) - len(alive)
    return RISK_CUBE * cube + RISK_MEAN * (1 - sum(shares) / len(shares)) + RISK_DEAD_TYPE * dead


def _sample_tray(rng, type_ids):
    types = [rng.choice(type_ids) for _ in range(3)]
    return types, [POSES[rng.choice(PIECE_TYPES[t])] for t in types]


class TrayBeamPolicy:
    """Przeszukuje całą tackę (wszystkie kolejności) wiązką na bitboardach."""

    name = "tray-beam-crn"

    def reset(self, game_seed):
        self.rng = random.Random(game_seed)

    def act(self, game, actions):
        occ = 0
        for r, row in enumerate(game.board.grid):
            for c, cell in enumerate(row):
                if cell:
                    occ |= 1 << (r * 8 + c)
        slots = [(i, POSES[p.index]) for i, p in enumerate(game.pieces) if p is not None]
        finals = _tray_finals(occ, slots)
        mixed = []
        while len(mixed) < MIXED_DRAWS:
            types, tray = _sample_tray(self.rng, ALL_TYPES)
            if not all(t in HARD_TYPES for t in types):
                mixed.append(tray)
        # Tacki samo-twarde są rzadkie (P = 1/27), więc losowane osobno, a nie w próbce mieszanej.
        hard = [_sample_tray(self.rng, HARD_TYPES)[1] for _ in range(HARD_DRAWS)]

        def review(final):
            value, _, board = final
            dead_mixed = sum(not _completable(board, tray) for tray in mixed) / MIXED_DRAWS
            dead_hard = sum(not _completable(board, tray) for tray in hard) / HARD_DRAWS
            return value - _risk(board) - DEATH * ((1 - P_HARD) * dead_mixed + P_HARD * dead_hard)

        move = max(finals, key=review)[1]
        return move if move in actions else actions[0]


def build(weights=None):
    return TrayBeamPolicy()
