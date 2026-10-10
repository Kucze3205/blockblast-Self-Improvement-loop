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


ROW_MASKS = [0xFF << (8 * y) for y in range(8)]
COL_MASKS = [sum(1 << (8 * y + x) for y in range(8)) for x in range(8)]
FULL = (1 << 64) - 1
NOT_COL0 = FULL & ~COL_MASKS[0]
NOT_COL7 = FULL & ~COL_MASKS[7]
FATAL = -1e6
BORDER = ROW_MASKS[0] | ROW_MASKS[7] | COL_MASKS[0] | COL_MASKS[7]
W_LINES, W_PERIMETER, W_ENCLOSED, W_MOBILITY = 0.76, -0.2, -0.5, 0.05
W_RISK, RISK_TOP = 20.0, 8
_placements = {}


def _piece_placements(piece):
    cached = _placements.get(piece.index)
    if cached is None:
        cells = [(dy, dx) for dy, row in enumerate(piece.shape) for dx, cell in enumerate(row) if cell]
        height, width = len(piece.shape), len(piece.shape[0])
        cached = {
            (x, y): sum(1 << (8 * (y + dy) + x + dx) for dy, dx in cells)
            for y in range(8 - height + 1)
            for x in range(8 - width + 1)
        }
        _placements[piece.index] = cached
    return cached


def _bitboard(grid):
    bits = 0
    for y, row in enumerate(grid):
        for x, cell in enumerate(row):
            if cell:
                bits |= 1 << (8 * y + x)
    return bits


def _clear_lines(bits):
    cleared, lines = 0, 0
    for mask in ROW_MASKS + COL_MASKS:
        if (bits & mask) == mask:
            cleared |= mask
            lines += 1
    return bits & ~cleared, lines


def _perimeter(bits):
    empty = FULL & ~bits
    return (
        (empty & COL_MASKS[0]).bit_count() + (empty & COL_MASKS[7]).bit_count()
        + (empty & ROW_MASKS[0]).bit_count() + (empty & ROW_MASKS[7]).bit_count()
        + (empty & (bits << 1) & NOT_COL0).bit_count() + (empty & (bits >> 1) & NOT_COL7).bit_count()
        + (empty & (bits << 8)).bit_count() + (empty & (bits >> 8)).bit_count()
    )


def _enclosed(bits):
    empty = FULL & ~bits
    reach = empty & BORDER
    while True:
        grow = (reach | ((reach << 1) & NOT_COL0) | ((reach >> 1) & NOT_COL7)
                | (reach << 8) | (reach >> 8)) & empty
        if grow == reach:
            return (empty & ~reach).bit_count()
        reach = grow


def _mobility(bits, piece):
    return sum(1 for mask in _piece_placements(piece).values() if (bits & mask) == 0)


_POSE_WEIGHTS = [
    (PIECE_POOL[index], 1 / (len(PIECE_TYPES) * len(poses)))
    for poses in PIECE_TYPES
    for index in poses
]


def _fresh_tray_death(bits):
    fit = sum(w for piece, w in _POSE_WEIGHTS
              if any((bits & mask) == 0 for mask in _piece_placements(piece).values()))
    return (1.0 - fit) ** 3


class LineMobilityPolicy:
    """Jeden ruch naprzód: linie, zwartość pustych pól i liczba miejsc dla zostałych klocków."""

    name = "line_mobility"

    def reset(self, game_seed):
        pass

    def act(self, game, actions):
        bits = _bitboard(game.board.grid)
        left = [(j, p) for j, p in enumerate(game.pieces) if p is not None]
        scored = []
        for action in actions:
            idx, x, y = action
            after, lines = _clear_lines(bits | _piece_placements(game.pieces[idx])[(x, y)])
            perimeter = _perimeter(after)
            enclosed = _enclosed(after)
            rest = [p for j, p in left if j != idx]
            mobility = sum(_mobility(after, p) for p in rest)
            score = (W_LINES * lines + W_PERIMETER * perimeter + W_ENCLOSED * enclosed
                     + W_MOBILITY * mobility)
            if rest and mobility == 0:
                score += FATAL
            scored.append((score, action, after))
        top = sorted(scored, key=lambda s: s[0], reverse=True)[:RISK_TOP]
        return max(top, key=lambda s: s[0] - W_RISK * _fresh_tray_death(s[2]))[1]


def build(weights):
    return LineMobilityPolicy()
