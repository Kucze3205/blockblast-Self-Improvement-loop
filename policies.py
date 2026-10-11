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


BEAM = 24
FINAL = 16
RISK_W = 300.0
POCKET_W = 6.0
TRANS_W = 1.0
LINE_W = 10.0
N = 8


def _fits(grid, shape, x, y):
    for dy, row in enumerate(shape):
        for dx, cell in enumerate(row):
            if cell and grid[y + dy][x + dx]:
                return False
    return True


def _positions(grid, shape):
    ph, pw = len(shape), len(shape[0])
    return [
        (x, y)
        for y in range(N - ph + 1)
        for x in range(N - pw + 1)
        if _fits(grid, shape, x, y)
    ]


def _place(grid, shape, x, y):
    g = [row[:] for row in grid]
    for dy, row in enumerate(shape):
        for dx, cell in enumerate(row):
            if cell:
                g[y + dy][x + dx] = 1
    rows = [r for r in range(N) if all(g[r])]
    cols = [c for c in range(N) if all(g[r][c] for r in range(N))]
    for r in rows:
        g[r] = [0] * N
    for c in cols:
        for r in range(N):
            g[r][c] = 0
    return g, len(rows) + len(cols)


def _pockets(grid):
    seen = [[False] * N for _ in range(N)]
    count = 0
    for sy in range(N):
        for sx in range(N):
            if grid[sy][sx] or seen[sy][sx]:
                continue
            seen[sy][sx] = True
            stack, size = [(sy, sx)], 0
            while stack:
                cy, cx = stack.pop()
                size += 1
                for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
                    if 0 <= ny < N and 0 <= nx < N and not grid[ny][nx] and not seen[ny][nx]:
                        seen[ny][nx] = True
                        stack.append((ny, nx))
            if size < 3:
                count += 1
    return count


def _trans(grid):
    t = 0
    for r in range(N):
        row = [1] + grid[r] + [1]
        t += sum(row[i] != row[i + 1] for i in range(N + 1))
    for c in range(N):
        col = [1] + [grid[r][c] for r in range(N)] + [1]
        t += sum(col[i] != col[i + 1] for i in range(N + 1))
    return t


def _fits_anywhere(grid, shape):
    ph, pw = len(shape), len(shape[0])
    for y in range(N - ph + 1):
        for x in range(N - pw + 1):
            if _fits(grid, shape, x, y):
                return True
    return False


def _piece_fail_prob(grid):
    fail = 0.0
    for poses in PIECE_TYPES:
        bad = sum(1 for i in poses if not _fits_anywhere(grid, PIECE_POOL[i].shape))
        fail += bad / len(poses)
    return fail / len(PIECE_TYPES)


def _plan(grid, slots):
    beam = [(0.0, 0, grid, ())]
    for _ in range(len(slots)):
        children = {}
        for _, lines_total, g, moves in beam:
            used = {m[0] for m in moves}
            for slot, shape in slots:
                if slot in used:
                    continue
                for x, y in _positions(g, shape):
                    ng, lines = _place(g, shape, x, y)
                    key = (frozenset(used | {slot}), tuple(map(tuple, ng)))
                    lt = lines_total + lines
                    sc = LINE_W * lt - TRANS_W * _trans(ng)
                    if key not in children or children[key][0] < sc:
                        children[key] = (sc, lt, ng, moves + ((slot, x, y),))
        if not children:
            return []
        beam = sorted(children.values(), key=lambda t: t[0], reverse=True)[:BEAM]
    return beam


def _choose(plans):
    best_total, best_move = None, None
    for sc, _, g, moves in sorted(plans, key=lambda t: t[0], reverse=True)[:FINAL]:
        total = sc - POCKET_W * _pockets(g) - RISK_W * (1 - (1 - _piece_fail_prob(g)) ** 3)
        if best_total is None or total > best_total:
            best_total, best_move = total, moves[0]
    return best_move


def _greedy_move(game, actions):
    best, best_val = actions[0], None
    for action in actions:
        idx, x, y = action
        g, lines = _place(game.board.grid, game.pieces[idx].shape, x, y)
        val = LINE_W * lines - TRANS_W * _trans(g) - POCKET_W * _pockets(g)
        if best_val is None or val > best_val:
            best, best_val = action, val
    return best


class SurvivalPolicy:
    name = "survival"

    def reset(self, game_seed):
        pass

    def act(self, game, actions):
        slots = [(i, p.shape) for i, p in enumerate(game.pieces) if p is not None]
        plans = _plan(game.board.grid, slots)
        if plans:
            return _choose(plans)
        return _greedy_move(game, actions)


def build(weights):
    return SurvivalPolicy()


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
