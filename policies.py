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


_FULL = (1 << 64) - 1
_ROW = [0xFF << (8 * r) for r in range(8)]
_COL = [sum(1 << (8 * r + c) for r in range(8)) for c in range(8)]
_NOT_COL0 = _FULL & ~_COL[0]
_NOT_COL7 = _FULL & ~_COL[7]
_NOT_ROW7 = _FULL & ~_ROW[7]
_RING = _ROW[0] | _ROW[7] | _COL[0] | _COL[7]
_LINE_W, _FILLED_W, _POCKET_W, _TRANS_W, _EDGE_W = 4.2, 1.4, 0.75, 1.5, 2.0
_FIT_CUBE_W, _FIT_MEAN_W, _DEAD_W = 400.0, 80.0, 12.3
_HARD_TYPES = (4, 6, 7, 10, 9)  # beam5, rect23, square3, corner5, L
_HARD_W, _HARD_SAMPLES, _DFS_BUDGET = 500.0, 16, 400
_BEAM, _FINAL, _CANDIDATES = 40, 12, 24


def _placements(pose):
    piece = PIECE_POOL[pose]
    h, w = len(piece.shape), len(piece.shape[0])
    cells = [(dy, dx) for dy, row in enumerate(piece.shape) for dx, cell in enumerate(row) if cell]
    out = []
    for y in range(9 - h):
        for x in range(9 - w):
            mask = 0
            for dy, dx in cells:
                mask |= 1 << (8 * (y + dy) + x + dx)
            out.append((mask, x, y))
    return out


_PLACEMENTS = [_placements(pose) for pose in range(len(PIECE_POOL))]


def _to_bits(grid):
    bits = 0
    for y, row in enumerate(grid):
        for x, cell in enumerate(row):
            if cell:
                bits |= 1 << (8 * y + x)
    return bits


def _clear(bits):
    gone = 0
    cleared = 0
    for m in _ROW:
        if (bits & m) == m:
            gone |= m
            cleared += 1
    for m in _COL:
        if (bits & m) == m:
            gone |= m
            cleared += 1
    return bits & ~gone, cleared


def _features(bits):
    left = (bits << 1) & _NOT_COL0
    right = (bits >> 1) & _NOT_COL7
    up = (bits << 8) & _FULL
    down = bits >> 8
    pockets = (left & right & up) | (left & right & down) | (left & up & down) | (right & up & down)
    trans = ((bits ^ (bits >> 1)) & _NOT_COL7).bit_count() + ((bits ^ (bits >> 8)) & _NOT_ROW7).bit_count()
    edge = (_RING & ~bits).bit_count()
    return bits.bit_count(), (pockets & ~bits).bit_count(), trans, edge


def _cheap(bits, lines):
    occ, pockets, trans, edge = _features(bits)
    return _LINE_W * lines - _FILLED_W * occ - _POCKET_W * pockets - _TRANS_W * trans - _EDGE_W * edge


def _any_fit(bits, pose):
    return any(not (bits & mask) for mask, _, _ in _PLACEMENTS[pose])


def _fit_penalty(bits):
    shares = []
    dead = 0
    for poses in PIECE_TYPES:
        fitting = sum(1 for pose in poses if _any_fit(bits, pose))
        shares.append(fitting / len(poses))
        if fitting == 0:
            dead += 1
    mean_all = sum(shares) / len(shares)
    alive = [share for share in shares if share > 0]
    mean_alive = sum(alive) / len(alive) if alive else 0.0
    return _FIT_CUBE_W * (1 - mean_alive) ** 3 + _FIT_MEAN_W * (1 - mean_all) + _DEAD_W * dead


def _playable(bits, poses, budget):
    if not poses:
        return True
    budget[0] -= 1
    if budget[0] < 0:
        return True
    for i, pose in enumerate(poses):
        rest = poses[:i] + poses[i + 1:]
        for mask, _, _ in _PLACEMENTS[pose]:
            if not (bits & mask):
                nxt, _ = _clear(bits | mask)
                if _playable(nxt, rest, budget):
                    return True
    return False


def _leaves(bits, remaining):
    frontier = [(bits, remaining, None, 0)]
    while True:
        children = []
        for b, rem, first, lines in frontier:
            for k, (slot, pose) in enumerate(rem):
                rest = rem[:k] + rem[k + 1:]
                for mask, x, y in _PLACEMENTS[pose]:
                    if not (b & mask):
                        nb, cleared = _clear(b | mask)
                        total = lines + cleared
                        children.append((_cheap(nb, total), nb, rest, total, first or (slot, x, y)))
        if not children:
            return []
        if not children[0][2]:
            return [(score, nb, move) for score, nb, _, _, move in children]
        children.sort(key=lambda child: child[0], reverse=True)
        frontier = [(nb, rest, move, total) for _, nb, rest, total, move in children[:_BEAM]]


def _hard_trays(rng):
    return [
        tuple(rng.choice(PIECE_TYPES[rng.choice(_HARD_TYPES)]) for _ in range(3))
        for _ in range(_HARD_SAMPLES)
    ]


class TrayBeamPolicy:
    name = "tray-beam"

    def __init__(self):
        self.reset(0)

    def reset(self, game_seed):
        self.rng = random.Random(f"tray:{game_seed}")

    def act(self, game, actions):
        bits = _to_bits(game.board.grid)
        remaining = tuple((idx, piece.index) for idx, piece in enumerate(game.pieces) if piece is not None)
        leaves = _leaves(bits, remaining)
        leaves.sort(key=lambda leaf: leaf[0], reverse=True)
        candidates = sorted(
            ((cheap - _fit_penalty(leaf_bits), leaf_bits, move) for cheap, leaf_bits, move in leaves[:_CANDIDATES]),
            key=lambda candidate: candidate[0],
            reverse=True,
        )
        trays = _hard_trays(self.rng)
        best_score, best_move = None, None
        for value, leaf_bits, move in candidates[:_FINAL]:
            bad = sum(1 for tray in trays if not _playable(leaf_bits, tray, [_DFS_BUDGET]))
            score = value - _HARD_W * bad / _HARD_SAMPLES
            if best_score is None or score > best_score:
                best_score, best_move = score, move
        return best_move if best_move is not None else actions[0]


def build(weights=None):
    return TrayBeamPolicy()
