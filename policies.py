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


BEAM_WIDTH = 3
RISK_FINALISTS = 3
RISK_SAMPLES = 10
DEATH_PENALTY = 1000.0
ROW_MASKS = [0xFF << (8 * r) for r in range(8)]
COL_MASKS = [sum(1 << (8 * r + c) for r in range(8)) for c in range(8)]
LINE_MASKS = ROW_MASKS + COL_MASKS


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
    agg = holes = bump = 0
    prev = 0
    for x in range(8):
        top = None
        for y in range(8):
            if (board >> (y * 8 + x)) & 1:
                if top is None:
                    top = y
            elif top is not None:
                holes += 1
        height = 0 if top is None else 8 - top
        agg += height
        if x:
            bump += abs(height - prev)
        prev = height
    return 4.0 * lines - 0.5 * agg - 0.8 * holes - 0.3 * bump


class TrayBeamPolicy:
    """Wiązka po pozostałych klockach tacki; końcówka tacki oceniana ryzykiem następnej."""

    name = "tray-beam"

    def reset(self, game_seed):
        self.rng = random.Random(f"risk:{game_seed}")

    def act(self, game, actions):
        board = _to_bits(game.board.grid)
        slots = tuple(i for i, piece in enumerate(game.pieces) if piece is not None)
        frontier = [(board, slots, None)]
        tray_ends = []
        dead_ends = []
        while frontier:
            children = []
            for b, rem, first in frontier:
                for slot in rem:
                    rest = tuple(s for s in rem if s != slot)
                    for x, y, mask in POSES[game.pieces[slot].index]:
                        if b & mask:
                            continue
                        nb, lines = _place_and_clear(b, mask)
                        move = first or (slot, x, y)
                        if not rest:
                            tray_ends.append((_value(nb, lines), nb, move))
                        elif not any(_fits(nb, game.pieces[s].index) for s in rest):
                            dead_ends.append((_value(nb, lines), nb, move))
                        else:
                            children.append((_value(nb, lines), nb, rest, move))
            children.sort(key=lambda e: e[0], reverse=True)
            frontier = [(nb, rest, move) for _, nb, rest, move in children[:BEAM_WIDTH]]

        if not tray_ends:
            return max(dead_ends, key=lambda e: e[0])[2]

        tray_ends.sort(key=lambda e: e[0], reverse=True)
        best_move, best_score = None, None
        for value, nb, move in tray_ends[:RISK_FINALISTS]:
            score = value - DEATH_PENALTY * self._death_rate(nb)
            if best_score is None or score > best_score:
                best_move, best_score = move, score
        return best_move

    def _death_rate(self, board):
        deaths = 0
        for _ in range(RISK_SAMPLES):
            tray = [self.rng.choice(self.rng.choice(PIECE_TYPES)) for _ in range(3)]
            if not any(_fits(board, idx) for idx in tray):
                deaths += 1
        return deaths / RISK_SAMPLES


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
