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


BEAM_WIDTH = 40
RISK_FINALISTS = 8
RISK_FINALISTS_TIGHT = 20
TIGHT_FREE_CELLS = 22
DEATH_WEIGHT = 400.0
RISK_LINEAR = 80.0
RISK_DEAD_TYPE = 12.3
STUCK_SAMPLES = 256
FULL = (1 << 64) - 1
ROW_MASKS = [0xFF << (8 * r) for r in range(8)]
COL_MASKS = [sum(1 << (8 * r + c) for r in range(8)) for c in range(8)]
LINE_MASKS = ROW_MASKS + COL_MASKS
EDGE_MASK = ROW_MASKS[0] | ROW_MASKS[7] | COL_MASKS[0] | COL_MASKS[7]
# Maski krawędzi, żeby przesunięcie bitowe nie zawijało się na sąsiedni wiersz.
NOT_LAST_COL = 0x7F7F7F7F7F7F7F7F
NOT_FIRST_COL = 0xFEFEFEFEFEFEFEFE
NOT_LAST_ROW = 0x00FFFFFFFFFFFFFF
NOT_FIRST_ROW = 0xFFFFFFFFFFFFFF00
POSE_PROBS = [
    (idx, 1.0 / (len(PIECE_TYPES) * len(pose_indices)))
    for pose_indices in PIECE_TYPES
    for idx in pose_indices
]
_TRAY_RNG = random.Random("stuck-trays")
# Stałe tacki: każdy finalista widzi te same losowania, więc różnice między nimi nie są szumem.
STUCK_TRAYS = [
    tuple(_TRAY_RNG.choice(_TRAY_RNG.choice(PIECE_TYPES)) for _ in range(3))
    for _ in range(STUCK_SAMPLES)
]


def _poses(piece):
    shape = piece.shape
    cells = [(dy, dx) for dy, row in enumerate(shape) for dx, cell in enumerate(row) if cell]
    out = []
    for y in range(8 - len(shape) + 1):
        for x in range(8 - len(shape[0]) + 1):
            mask = 0
            for dy, dx in cells:
                mask |= 1 << ((y + dy) * 8 + x + dx)
            out.append((x, y, mask))
    return out


POSES = {piece.index: _poses(piece) for piece in PIECE_POOL}


def _to_bits(grid):
    bits = 0
    for y in range(8):
        for x in range(8):
            if grid[y][x]:
                bits |= 1 << (y * 8 + x)
    return bits


def _place_and_clear(board, mask):
    board |= mask
    cleared = 0
    lines = 0
    for line in LINE_MASKS:
        if (board & line) == line:
            cleared |= line
            lines += 1
    return board & ~cleared, lines


def _fits(board, piece_index):
    return any(not board & mask for _, _, mask in POSES[piece_index])


def _value(board, lines):
    # Bez grawitacji czyszczenie nie opuszcza stosu, więc wysokości i dziury od osi y karałyby czyszczenie.
    empty = FULL & ~board
    has_empty_neighbour = (
        ((empty >> 1) & NOT_LAST_COL)
        | ((empty << 1) & NOT_FIRST_COL)
        | (empty >> 8)
        | ((empty << 8) & NOT_FIRST_ROW)
    )
    isolated = empty & ~has_empty_neighbour
    transitions = (
        ((board ^ (board >> 1)) & NOT_LAST_COL).bit_count()
        + ((board ^ (board >> 8)) & NOT_LAST_ROW).bit_count()
    )
    return (
        4.2 * lines
        - 1.4 * board.bit_count()
        - 0.75 * isolated.bit_count()
        - 1.5 * transitions
        - 2.0 * (empty & EDGE_MASK).bit_count()
    )


class TrayBeamPolicy:
    """Wiązka po pozostałych klockach tacki; końcówka tacki oceniana ryzykiem następnej."""

    name = "tray-beam"

    def reset(self, game_seed):
        pass

    def act(self, game, actions):
        root = _to_bits(game.board.grid)
        slots = tuple(i for i, piece in enumerate(game.pieces) if piece is not None)
        frontier = [(root, slots, None, 0)]
        tray_ends = []
        dead_ends = []
        while frontier:
            children = []
            for b, rem, first, lines_so_far in frontier:
                for slot in rem:
                    rest = tuple(s for s in rem if s != slot)
                    for x, y, mask in POSES[game.pieces[slot].index]:
                        if b & mask:
                            continue
                        nb, lines = _place_and_clear(b, mask)
                        total = lines_so_far + lines
                        move = first or (slot, x, y)
                        if not rest:
                            tray_ends.append((_value(nb, total), nb, move))
                        elif not any(_fits(nb, game.pieces[s].index) for s in rest):
                            dead_ends.append((_value(nb, total), nb, move))
                        else:
                            children.append((_value(nb, total), nb, rest, total, move))
            children.sort(key=lambda e: e[0], reverse=True)
            frontier = [(nb, rest, move, total) for _, nb, rest, total, move in children[:BEAM_WIDTH]]

        if not tray_ends:
            return max(dead_ends, key=lambda e: e[0])[2]

        free = 64 - root.bit_count()
        finalists = RISK_FINALISTS_TIGHT if free <= TIGHT_FREE_CELLS else RISK_FINALISTS
        tray_ends.sort(key=lambda e: e[0], reverse=True)
        best_move, best_score = None, None
        for value, nb, move in tray_ends[:finalists]:
            score = value - _risk(nb)
            if best_score is None or score > best_score:
                best_move, best_score = move, score
        return best_move


def _fit_profile(board):
    fitting = {idx for idx, _ in POSE_PROBS if _fits(board, idx)}
    miss = sum(prob for idx, prob in POSE_PROBS if idx not in fitting)
    dead_types = sum(1 for poses in PIECE_TYPES if fitting.isdisjoint(poses))
    return miss, dead_types


def _completable(board, pieces):
    if not pieces:
        return True
    for k, idx in enumerate(pieces):
        rest = pieces[:k] + pieces[k + 1:]
        for _, _, mask in POSES[idx]:
            if board & mask:
                continue
            nxt, _ = _place_and_clear(board, mask)
            if _completable(nxt, rest):
                return True
    return False


def _stuck_share(board):
    stuck = 0
    for tray in STUCK_TRAYS:
        if any(_fits(board, idx) for idx in tray) and not _completable(board, tray):
            stuck += 1
    return stuck / len(STUCK_TRAYS)


def _risk(board):
    # Martwa tacka: żaden klocek się nie mieści (miss**3, klocki niezależne) albo nie da się jej ułożyć.
    miss, dead_types = _fit_profile(board)
    death = miss ** 3 + _stuck_share(board)
    return DEATH_WEIGHT * death + RISK_LINEAR * miss + RISK_DEAD_TYPE * dead_types


def build(weights=None):
    return TrayBeamPolicy()


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
