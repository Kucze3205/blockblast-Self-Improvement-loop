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


def _popcount(bits):
    return bin(bits).count("1")


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
    for i, piece in enumerate(pieces):
        rest = pieces[:i] + pieces[i + 1:]
        for mask in _placements(piece).values():
            if not (bits & mask):
                after, _ = _place_and_clear(bits, mask)
                if _tray_playable(after, rest):
                    return True
    return False


_FULL = (1 << 64) - 1
_COL0 = sum(1 << (8 * y) for y in range(8))
_COL7 = _COL0 << 7
_EDGE = _COL0 | _COL7 | 0xFF | (0xFF << 56)
_NOT_COL0 = _FULL & ~_COL0
_NOT_COL7 = _FULL & ~_COL7
_ROWS_0_TO_6 = (1 << 56) - 1

LINE_WEIGHT = 4.2
CLEARED_CELL_WEIGHT = 1.4
ISOLATED_WEIGHT = 0.75
TRANSITION_WEIGHT = 1.5
BOUNDARY_WEIGHT = 2.0
POCKET_WEIGHT = 6.0
BEAM_WIDTH = 24
FINALISTS = 8
FINALISTS_TIGHT = 20
TIGHT_FREE_CELLS = 22
LAMBDA_DEATH = 1000.0
CLOSE_SAMPLES = 256

_TYPE_MASKS = []


def _type_masks():
    if not _TYPE_MASKS:
        for type_indices in PIECE_TYPES:
            _TYPE_MASKS.append([list(_placements(PIECE_POOL[i]).values()) for i in type_indices])
    return _TYPE_MASKS


def _fit_penalty(bits):
    """Kara za klocki bez miejsca: szansa dopasowania po typach generatora i kara za martwe typy."""
    fits = []
    for poses in _type_masks():
        fitting = sum(1 for masks in poses if any(not (bits & m) for m in masks))
        fits.append(fitting / len(poses))
    alive = [f for f in fits if f > 0]
    avg_alive = sum(alive) / len(alive) if alive else 0.0
    avg_all = sum(fits) / len(fits)
    return 400 * (1 - avg_alive) ** 3 + 80 * (1 - avg_all) + 12.3 * (len(fits) - len(alive))


def _structure_cost(bits):
    free = _FULL & ~bits
    neighbours = ((free << 1) & _NOT_COL0) | ((free >> 1) & _NOT_COL7) | (free << 8) | (free >> 8)
    isolated = _popcount(free & ~neighbours)
    transitions = _popcount((bits ^ (bits >> 1)) & _NOT_COL7) + _popcount((bits ^ (bits >> 8)) & _ROWS_0_TO_6)
    boundary_empty = _popcount(free & _EDGE)
    return ISOLATED_WEIGHT * isolated + TRANSITION_WEIGHT * transitions + BOUNDARY_WEIGHT * boundary_empty


def _place_gain(bits, mask):
    placed = bits | mask
    after, lines = _place_and_clear(bits, mask)
    cleared = _popcount(placed) - _popcount(after)
    return after, LINE_WEIGHT * lines + CLEARED_CELL_WEIGHT * cleared


def _sample_tray(rng):
    return tuple(PIECE_POOL[rng.choice(rng.choice(PIECE_TYPES))] for _ in range(3))


def _stuck_share(bits, samples):
    stuck = 0
    for tray in samples:
        # Tacka bez żadnego pasującego klocka nie wlicza się: jej karę niesie już _fit_penalty.
        fits = any(not (bits & m) for p in tray for m in _placements(p).values())
        if fits and not _tray_playable(bits, tray):
            stuck += 1
    return stuck / len(samples)


def _plan_values(bits, pieces, samples):
    """Najlepsza wartość pełnego planu dla każdego pierwszego ruchu tacki."""
    slots = [i for i, p in enumerate(pieces) if p is not None]
    if not slots:
        return {}
    finalists = FINALISTS_TIGHT if 64 - _popcount(bits) <= TIGHT_FREE_CELLS else FINALISTS
    frontier = [(0.0, bits, None, ())]
    for depth in range(len(slots)):
        children = []
        for value, board, first, used in frontier:
            for slot in slots:
                if slot in used:
                    continue
                for (x, y), mask in _placements(pieces[slot]).items():
                    if board & mask:
                        continue
                    after, gain = _place_gain(board, mask)
                    children.append((
                        value + gain - _structure_cost(after),
                        after,
                        first if first is not None else (slot, x, y),
                        used + (slot,),
                    ))
        children.sort(key=lambda child: child[0], reverse=True)
        if depth == len(slots) - 1:
            values = {}
            for value, after, first, _ in children[:finalists]:
                full = (
                    value
                    - _fit_penalty(after)
                    - POCKET_WEIGHT * _pocket_cells(after)
                    - LAMBDA_DEATH * _stuck_share(after, samples)
                )
                values[first] = max(values.get(first, float("-inf")), full)
            return values
        frontier = []
        for child in children:
            remaining = [pieces[s] for s in slots if s not in child[3]]
            if _tray_playable(child[1], remaining):
                frontier.append(child)
                if len(frontier) == BEAM_WIDTH:
                    break


class TrayBeamPolicy:
    """Wiązka po całej tacce; liść z liniami i strukturą, finaliści z karami za dopasowanie i następną tackę."""

    name = "tray_beam"

    def reset(self, game_seed):
        # Inny strumień niż Generator gry, inaczej polityka widziałaby przyszłe tacki.
        self.rng = random.Random(f"closability:{game_seed}")

    def act(self, game, actions):
        samples = [_sample_tray(self.rng) for _ in range(CLOSE_SAMPLES)]
        values = _plan_values(_to_bits(game.board.grid), list(game.pieces), samples)
        scores = {action: values.get(action, float("-inf")) for action in actions}
        top = max(scores.values())
        ties = [action for action in actions if scores[action] == top]
        if len(ties) == 1:
            return ties[0]
        return max(ties, key=lambda action: _immediate_gain(game, action))


def build(weights):
    # Sygnatura z ewaluatora; polityka nie ma wag, więc argument jest ignorowany.
    return TrayBeamPolicy()
