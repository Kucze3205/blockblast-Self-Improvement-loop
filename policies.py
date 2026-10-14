"""
Polityki grające, których używa benchmark.

Wszystkie są deterministyczne przy zadanym seedzie partii — benchmark mierzy,
co polityka umie, a nie jak wypada w trakcie nauki (#8).
"""
import random

from board import Board
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


STRIDE, W, H = 9, 8, 8  # bit = y*STRIDE + x; kolumna 8 to strażnik, nigdy nie zajęta
BEAM = 8
DEATH_W = 1000.0
DEAD_W = 6.0
POOL = 16
EDGE_PENALTY = 2.0
CELL_W = 1.4
LINE_W = 4.2
_ROW = [sum(1 << (y * STRIDE + x) for x in range(W)) for y in range(H)]
_COL = [sum(1 << (y * STRIDE + x) for y in range(H)) for x in range(W)]
_BORDER = sum(
    1 << (y * STRIDE + x)
    for y in range(H)
    for x in range(W)
    if x in (0, W - 1) or y in (0, H - 1)
)
_PLAN = []
for _piece in PIECE_POOL:
    _shape = _piece.shape
    _h, _w = len(_shape), len(_shape[0])
    _offs = [r * STRIDE + c for r, row in enumerate(_shape) for c, v in enumerate(row) if v]
    _pmask = sum(1 << o for o in _offs)
    _inside = sum(1 << (y * STRIDE + x) for y in range(H - _h + 1) for x in range(W - _w + 1))
    _PLAN.append((_offs, _pmask, _inside, len(_offs)))
_POSE_PROB = [0.0] * len(PIECE_POOL)
for _poses in PIECE_TYPES:
    for _p in _poses:
        _POSE_PROB[_p] = 1.0 / (len(PIECE_TYPES) * len(_poses))


def _occupancy(board):
    occ = 0
    for y, row in enumerate(board.grid):
        for x, cell in enumerate(row):
            if cell:
                occ |= 1 << (y * STRIDE + x)
    return occ


def _anchors(occ, pose):
    offs, _, inside, _ = _PLAN[pose]
    blocked = 0
    for o in offs:
        blocked |= occ >> o
    return inside & ~blocked


def _place(occ, pose, anchor):
    occ |= _PLAN[pose][1] << anchor
    clear = 0
    lines = 0
    for m in _ROW:
        if (occ & m) == m:
            clear |= m
            lines += 1
    for m in _COL:
        if (occ & m) == m:
            clear |= m
            lines += 1
    return occ & ~clear, lines


def _dead_types(occ):
    dead = 0
    for poses in PIECE_TYPES:
        for pose in poses:
            if _anchors(occ, pose):
                break
        else:
            dead += 1
    return dead


def _dead_tray_prob(occ):
    q = 0.0
    for pose, prob in enumerate(_POSE_PROB):
        if not _anchors(occ, pose):
            q += prob
    return q ** 3


class TrayBeamPolicy:
    name = "tray_beam"

    def reset(self, game_seed):
        pass

    def act(self, game, actions):
        occ = _occupancy(game.board)
        slots = tuple(i for i, p in enumerate(game.pieces) if p is not None)
        beam = [((0, 0.0), 0.0, occ, slots, None)]
        terminal = []
        while True:
            nxt = {}
            for _, score, occ_s, rest, first in beam:
                for slot in rest:
                    pose = game.pieces[slot].index
                    left = tuple(r for r in rest if r != slot)
                    cells = _PLAN[pose][3]
                    anchors = _anchors(occ_s, pose)
                    while anchors:
                        low = anchors & -anchors
                        anchor = low.bit_length() - 1
                        anchors ^= low
                        new_occ, lines = _place(occ_s, pose, anchor)
                        s = score + CELL_W * cells + LINE_W * lines
                        s -= EDGE_PENALTY * (~new_occ & _BORDER).bit_count()
                        head = first or (slot, anchor % STRIDE, anchor // STRIDE)
                        if not left:
                            terminal.append((s, new_occ, head))
                            continue
                        unfit = sum(1 for r in left if not _anchors(new_occ, game.pieces[r].index))
                        rank = (unfit, -s)
                        key = (new_occ, left)
                        if key not in nxt or rank < nxt[key][0]:
                            nxt[key] = (rank, s, new_occ, left, head)
            if not nxt:
                break
            pool = sorted(nxt.values(), key=lambda t: t[0])[:POOL]
            beam = []
            for (unfit, _), s, new_occ, left, head in pool:
                s -= DEAD_W * _dead_types(new_occ)
                beam.append(((unfit, -s), s, new_occ, left, head))
            beam = sorted(beam, key=lambda t: t[0])[:BEAM]
        if not terminal:
            return beam[0][4] or actions[0]
        best_value, best_head = None, None
        for s, new_occ, head in sorted(terminal, key=lambda t: -t[0])[:POOL]:
            value = s - DEAD_W * _dead_types(new_occ) - DEATH_W * _dead_tray_prob(new_occ)
            if best_value is None or value > best_value:
                best_value, best_head = value, head
        return best_head


def build(weights):
    return TrayBeamPolicy()
