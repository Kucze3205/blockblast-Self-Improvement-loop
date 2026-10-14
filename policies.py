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


W, H = Board.WIDTH, Board.HEIGHT
FULL = (1 << (W * H)) - 1
ROW_MASKS = [((1 << W) - 1) << (W * r) for r in range(H)]
COL_MASKS = [sum(1 << (W * r + c) for r in range(H)) for c in range(W)]
LINE_MASKS = ROW_MASKS + COL_MASKS
NOT_LEFT = FULL & ~COL_MASKS[0]
NOT_RIGHT = FULL & ~COL_MASKS[W - 1]
HMASK = sum(1 << (W * r + c) for r in range(H) for c in range(1, W))
VMASK = sum(1 << (W * r + c) for r in range(H - 1) for c in range(W))

CLEAR_W = 10.0
TRANSITION_W = 1.0
ISOLATED_W = 6.0
RISK_W = 300.0
BEAM = 24
FINAL = 16


def _placements(shape):
    h, w = len(shape), len(shape[0])
    cells = [(dy, dx) for dy, row in enumerate(shape) for dx, cell in enumerate(row) if cell]
    out = []
    for y in range(H - h + 1):
        for x in range(W - w + 1):
            mask = 0
            for dy, dx in cells:
                mask |= 1 << (W * (y + dy) + x + dx)
            out.append((x, y, mask))
    return out


POSE_PLACEMENTS = [_placements(piece.shape) for piece in PIECE_POOL]
POSE_PROBABILITY = [
    1.0 / (len(PIECE_TYPES) * len(PIECE_TYPES[piece.type_index])) for piece in PIECE_POOL
]


def _bits(grid):
    board = 0
    for r, row in enumerate(grid):
        for c, cell in enumerate(row):
            if cell:
                board |= 1 << (W * r + c)
    return board


def _clear(board):
    cleared, clear_mask = 0, 0
    for mask in LINE_MASKS:
        if (board & mask) == mask:
            cleared += 1
            clear_mask |= mask
    return board & ~clear_mask, cleared


def _fits(board, pose):
    return any((board & mask) == 0 for _, _, mask in POSE_PLACEMENTS[pose])


def _transitions(board):
    return (((board ^ (board << 1)) & HMASK).bit_count()
            + ((board ^ (board >> W)) & VMASK).bit_count())


def _isolated(board):
    empty = FULL & ~board
    touching = (
        ((empty << 1) & NOT_LEFT)
        | ((empty >> 1) & NOT_RIGHT)
        | ((empty << W) & FULL)
        | (empty >> W)
    )
    return (empty & ~touching).bit_count()


def _beam_score(board, lines):
    return CLEAR_W * lines - TRANSITION_W * _transitions(board)


def _risk(board):
    q = sum(POSE_PROBABILITY[pose] for pose in range(len(PIECE_POOL)) if not _fits(board, pose))
    return 1.0 - (1.0 - q) ** 3


def _plan(board, pieces):
    beam = [(0, board, 0, pieces, None)]
    for _ in pieces:
        children = []
        for _, b, lines, rest, first in beam:
            for pos, (tray_idx, pose) in enumerate(rest):
                left = rest[:pos] + rest[pos + 1:]
                for x, y, mask in POSE_PLACEMENTS[pose]:
                    if b & mask:
                        continue
                    nxt, cleared = _clear(b | mask)
                    if left and not any(_fits(nxt, other) for _, other in left):
                        continue
                    total = lines + cleared
                    move = first if first is not None else (tray_idx, x, y)
                    children.append((_beam_score(nxt, total), nxt, total, left, move))
        children.sort(key=lambda child: -child[0])
        beam = children[:BEAM]
    best_value, best_move = None, None
    for score, b, _, _, move in beam[:FINAL]:
        value = score - ISOLATED_W*_isolated(b) - RISK_W*_risk(b)
        if best_value is None or value > best_value:
            best_value, best_move = value, move
    return best_move


class TrayPolicy:
    name = "tray"

    def reset(self, game_seed):
        pass

    def act(self, game, actions):
        board = _bits(game.board.grid)
        pieces = tuple((idx, piece.index) for idx, piece in enumerate(game.pieces) if piece is not None)
        move = _plan(board, pieces)
        return move if move is not None else actions[0]


def build(weights):
    # Polityka nie czyta wag; argument zostaje, bo ewaluator woła build(weights).
    return TrayPolicy()
