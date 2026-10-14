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
POOL = 16
LINE_W = 4.2
OCC_W = 1.4
ISO_W = 0.75
TRANS_W = 1.5
EDGE_W = 2.0
DEAD_W = 6.0
DEATH_W = 1000.0
STUCK_W = 1000.0
DRAWS = 64
_BOARD = sum(1 << (y * STRIDE + x) for y in range(H) for x in range(W))
_HPAIR = sum(1 << (y * STRIDE + x) for y in range(H) for x in range(W - 1))
_VPAIR = sum(1 << (y * STRIDE + x) for y in range(H - 1) for x in range(W))
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


def _board_cost(occ):
    empty = _BOARD & ~occ
    empty_nb = (empty >> 1) | (empty << 1) | (empty >> STRIDE) | (empty << STRIDE)
    isolated = (empty & ~empty_nb).bit_count()
    transitions = ((occ ^ (occ >> 1)) & _HPAIR).bit_count() + ((occ ^ (occ >> STRIDE)) & _VPAIR).bit_count()
    border = (empty & _BORDER).bit_count()
    return OCC_W * occ.bit_count() + ISO_W * isolated + TRANS_W * transitions + EDGE_W * border


def _cheap(occ, lines):
    return LINE_W * lines - _board_cost(occ)


def _risk(occ):
    fit = [bool(_anchors(occ, p)) for p in range(len(PIECE_POOL))]
    q = sum(prob for p, prob in enumerate(_POSE_PROB) if not fit[p])
    dead = sum(1 for poses in PIECE_TYPES if not any(fit[p] for p in poses))
    return q, dead


def _full_value(occ, lines):
    q, dead = _risk(occ)
    return _cheap(occ, lines) - DEAD_W * dead - DEATH_W * q ** 3


def _placeable(occ, poses):
    if len(poses) == 1:
        return _anchors(occ, poses[0]) != 0
    for i, pose in enumerate(poses):
        rest = poses[:i] + poses[i + 1:]
        anchors = _anchors(occ, pose)
        while anchors:
            low = anchors & -anchors
            anchors ^= low
            if _placeable(_place(occ, pose, low.bit_length() - 1)[0], rest):
                return True
    return False


def _draw_tray(rng):
    return tuple(rng.choice(rng.choice(PIECE_TYPES)) for _ in range(3))


def _stuck_share(occ, trays):
    stuck = 0
    for tray in trays:
        # tacka bez pasującego klocka osobno jest już w DEATH_W·q³
        if any(_anchors(occ, p) for p in tray) and not _placeable(occ, tray):
            stuck += 1
    return stuck / len(trays)


class TrayBeamPolicy:
    name = "tray_beam_risk"

    def reset(self, game_seed):
        self.rng = random.Random(f"tray:{game_seed}")

    def act(self, game, actions):
        occ = _occupancy(game.board)
        slots = tuple(i for i, p in enumerate(game.pieces) if p is not None)
        beam = [(0, occ, slots, None)]
        terminal = []
        partial = actions[0]
        while beam:
            nxt = {}
            for lines, occ_s, rest, first in beam:
                for slot in rest:
                    pose = game.pieces[slot].index
                    left = tuple(r for r in rest if r != slot)
                    anchors = _anchors(occ_s, pose)
                    while anchors:
                        low = anchors & -anchors
                        anchors ^= low
                        anchor = low.bit_length() - 1
                        new_occ, placed = _place(occ_s, pose, anchor)
                        total = lines + placed
                        head = first or (slot, anchor % STRIDE, anchor // STRIDE)
                        if not left:
                            terminal.append((_cheap(new_occ, total), new_occ, total, head))
                            continue
                        unfit = sum(1 for r in left if not _anchors(new_occ, game.pieces[r].index))
                        cheap = _cheap(new_occ, total)
                        key = (new_occ, left)
                        if key not in nxt or (unfit, -cheap) < nxt[key][:2]:
                            nxt[key] = (unfit, -cheap, total, new_occ, left, head)
            pool = sorted(nxt.values(), key=lambda t: t[:2])[:POOL]
            if pool:
                partial = pool[0][5]
            beam = []
            for unfit, _, total, new_occ, left, head in pool:
                value = _full_value(new_occ, total)
                beam.append(((unfit, -value), total, new_occ, left, head))
            beam = sorted(beam, key=lambda t: t[0])[:BEAM]
            beam = [(total, occ_b, left, head) for _, total, occ_b, left, head in beam]
        if not terminal:
            return partial
        finalists = sorted(terminal, key=lambda t: -t[0])[:POOL]
        trays = [_draw_tray(self.rng) for _ in range(DRAWS)]
        return max(
            finalists,
            key=lambda t: _full_value(t[1], t[2]) - STUCK_W * _stuck_share(t[1], trays),
        )[3]


def build(weights):
    return TrayBeamPolicy()
