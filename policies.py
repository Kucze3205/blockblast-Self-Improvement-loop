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
ALL_LINE_MASKS = ROW_MASKS + COL_MASKS
_PLACEMENTS = {}


def _placements(piece):
    key = tuple(tuple(row) for row in piece.shape)
    if key not in _PLACEMENTS:
        h, w = len(key), len(key[0])
        table = {}
        for y in range(8 - h + 1):
            for x in range(8 - w + 1):
                mask = 0
                for dy, row in enumerate(key):
                    for dx, cell in enumerate(row):
                        if cell:
                            mask |= 1 << ((y + dy) * 8 + x + dx)
                table[(x, y)] = mask
        _PLACEMENTS[key] = table
    return _PLACEMENTS[key]


def _to_bits(grid):
    bits = 0
    for y, row in enumerate(grid):
        for x, cell in enumerate(row):
            if cell:
                bits |= 1 << (y * 8 + x)
    return bits


def _place_and_clear(bits, mask):
    bits |= mask
    lines = [m for m in ALL_LINE_MASKS if (bits & m) == m]
    drop = 0
    for m in lines:
        drop |= m
    return bits & ~drop, len(lines)


def _pocket_cells(bits):
    """Puste pola w obszarach mniejszych niż najmniejszy klocek trzykomórkowy."""
    free = [not ((bits >> i) & 1) for i in range(64)]
    seen = [False] * 64
    pockets = 0
    for start in range(64):
        if not free[start] or seen[start]:
            continue
        seen[start] = True
        stack, size = [start], 0
        while stack:
            i = stack.pop()
            size += 1
            y, x = divmod(i, 8)
            for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                if 0 <= ny < 8 and 0 <= nx < 8:
                    j = ny * 8 + nx
                    if free[j] and not seen[j]:
                        seen[j] = True
                        stack.append(j)
        if size < 3:
            pockets += size
    return pockets


def _tray_playable(bits, pieces):
    if not pieces:
        return True
    for mask in _placements(pieces[0]).values():
        if not (bits & mask):
            after, _ = _place_and_clear(bits, mask)
            if _tray_playable(after, pieces[1:]):
                return True
    return False


_FIT_TABLE = []


def _fit_table():
    if not _FIT_TABLE:
        for type_indices in PIECE_TYPES:
            share = 1 / (len(PIECE_TYPES) * len(type_indices))
            for index in type_indices:
                _FIT_TABLE.append((share, list(_placements(PIECE_POOL[index]).values())))
    return _FIT_TABLE


def _fit_probability(bits):
    """Prawdopodobieństwo, że losowy klocek z generatora mieści się na planszy."""
    return sum(share for share, masks in _fit_table() if any(not (bits & m) for m in masks))


class SurvivalPolicy:
    """Przeżycie przed punktami: tacka zostaje układalna, potem większa szansa na zmieszczenie
    losowego klocka, potem mniej pustych pól w kieszeniach, potem więcej linii. Punkty to remis."""

    name = "survival"

    def reset(self, game_seed):
        pass

    def act(self, game, actions):
        bits = _to_bits(game.board.grid)
        best, best_key = actions[0], None
        for action in actions:
            key = self._key(game, bits, action)
            if best_key is None or key > best_key:
                best, best_key = action, key
        return best

    def _key(self, game, bits, action):
        idx, x, y = action
        piece = game.pieces[idx]
        after, lines = _place_and_clear(bits, _placements(piece)[(x, y)])
        rest = [p for j, p in enumerate(game.pieces) if j != idx and p is not None]
        return (
            _tray_playable(after, rest),
            _fit_probability(after),
            -_pocket_cells(after),
            lines,
            _immediate_gain(game, action),
        )


def build(weights):
    # Sygnatura z ewaluatora; polityka nie ma wag, więc argument jest ignorowany.
    return SurvivalPolicy()
