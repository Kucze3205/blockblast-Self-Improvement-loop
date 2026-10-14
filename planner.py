"""Planer tacki na bitboardach: wiązka po klockach tacki i ryzyko następnej tacki."""
import random

from board import Board
from pieces import PIECE_POOL, PIECE_TYPES

W, H = Board.WIDTH, Board.HEIGHT
ROW = [0xFF << (W * r) for r in range(H)]
COL = [sum(1 << (W * r + c) for r in range(H)) for c in range(W)]

DEATH_W = 400.0
TRANS_W = 1.0
FILL_W = 0.5
LINE_W = 10.0
BEAM = 24
FINALISTS = 8
TRAY_SAMPLES = 24
JOINT_BUDGET = 3000
TRAY_SIZE = 3

TRANS_ROW = [
    sum(((v >> i) & 1) != ((v >> (i + 1)) & 1) for i in range(W - 1))
    for v in range(1 << W)
]


def _placements(shape):
    h, w = len(shape), len(shape[0])
    cells = [(dy, dx) for dy, row in enumerate(shape) for dx, cell in enumerate(row) if cell]
    out = []
    for y in range(H - h + 1):
        for x in range(W - w + 1):
            mask = 0
            for dy, dx in cells:
                mask |= 1 << ((y + dy) * W + x + dx)
            out.append((x, y, mask))
    return out


PLACEMENTS = [_placements(piece.shape) for piece in PIECE_POOL]
MASKS = [[mask for _, _, mask in plc] for plc in PLACEMENTS]

POSE_WEIGHT = [0.0] * len(PIECE_POOL)
for _poses in PIECE_TYPES:
    for _pose in _poses:
        POSE_WEIGHT[_pose] = 1.0 / (len(PIECE_TYPES) * len(_poses))


def to_bits(grid):
    bits = 0
    for y, row in enumerate(grid):
        for x, cell in enumerate(row):
            if cell:
                bits |= 1 << (W * y + x)
    return bits


def transpose(b):
    t = (b ^ (b >> 7)) & 0x00AA00AA00AA00AA
    b ^= t ^ (t << 7)
    t = (b ^ (b >> 14)) & 0x0000CCCC0000CCCC
    b ^= t ^ (t << 14)
    t = (b ^ (b >> 28)) & 0x00000000F0F0F0F0
    b ^= t ^ (t << 28)
    return b


def clear(b):
    bt = transpose(b)
    mask = 0
    lines = 0
    for r in range(H):
        if ((b >> (W * r)) & 0xFF) == 0xFF:
            mask |= ROW[r]
            lines += 1
    for c in range(W):
        if ((bt >> (H * c)) & 0xFF) == 0xFF:
            mask |= COL[c]
            lines += 1
    return b & ~mask, lines


def trans(b):
    bt = transpose(b)
    total = 0
    for r in range(H):
        total += TRANS_ROW[(b >> (W * r)) & 0xFF] + TRANS_ROW[(bt >> (H * r)) & 0xFF]
    return total


def fits(b, pose):
    for m in MASKS[pose]:
        if not (b & m):
            return True
    return False


def single_risk(b):
    return sum(POSE_WEIGHT[p] for p in range(len(PIECE_POOL)) if not fits(b, p))


def places_all(b, poses, budget):
    if not poses:
        return True
    tried = set()
    for k, pose in enumerate(poses):
        if pose in tried:
            continue
        tried.add(pose)
        rest = poses[:k] + poses[k + 1:]
        for m in MASKS[pose]:
            if b & m:
                continue
            budget[0] -= 1
            if budget[0] <= 0:
                return True
            if places_all(clear(b | m)[0], rest, budget):
                return True
    return False


def dead_prob(b, trays):
    p_single = 1.0 - (1.0 - single_risk(b)) ** TRAY_SIZE
    stuck_n = stuck_dead = fit_n = fit_dead = 0
    for tray in trays:
        dead = not places_all(b, tray, [JOINT_BUDGET])
        if all(fits(b, p) for p in tray):
            fit_n += 1
            fit_dead += dead
        else:
            stuck_n += 1
            stuck_dead += dead
    d_stuck = stuck_dead / stuck_n if stuck_n else 1.0
    q = fit_dead / fit_n if fit_n else 0.0
    return p_single * d_stuck + (1.0 - p_single) * q


def _cheap(b, lines):
    return LINE_W * lines - TRANS_W * trans(b) - FILL_W * b.bit_count()


def _expand(state):
    _, b, rest, first, lines = state
    out = []
    for k, (slot, pose) in enumerate(rest):
        left = rest[:k] + rest[k + 1:]
        for x, y, m in PLACEMENTS[pose]:
            if b & m:
                continue
            nb, n = clear(b | m)
            total = lines + n
            out.append((_cheap(nb, total), nb, left, first or (slot, x, y), total))
    return out


def search(board, slots):
    frontier = [(0.0, board, tuple(slots), None, 0)]
    complete, dead = [], []
    while frontier:
        nxt = []
        for state in frontier:
            kids = _expand(state)
            if not kids:
                dead.append(state[3])
            for kid in kids:
                (nxt if kid[2] else complete).append(kid)
        frontier = sorted(nxt, key=lambda s: s[0], reverse=True)[:BEAM]
    return complete, dead


def plan_move(board, slots, trays):
    complete, dead = search(board, slots)
    best = {}
    for cheap, nb, _, first, _ in complete:
        if first not in best or cheap > best[first][0]:
            best[first] = (cheap, nb)
    finalists = sorted(best.items(), key=lambda kv: kv[1][0], reverse=True)[:FINALISTS]
    scored = [
        (cheap - DEATH_W * dead_prob(nb, trays), first)
        for first, (cheap, nb) in finalists
    ]
    scored += [(-DEATH_W, first) for first in set(dead) if first not in best]
    return max(scored, key=lambda s: s[0])[1]


class TrayPlanner:
    name = "tray-planner"

    def __init__(self):
        self._rng = random.Random(0)

    def reset(self, game_seed):
        self._rng = random.Random(f"tray-planner:{game_seed}")

    def _draw_tray(self):
        return tuple(self._rng.choice(self._rng.choice(PIECE_TYPES)) for _ in range(TRAY_SIZE))

    def act(self, game, actions):
        board = to_bits(game.board.grid)
        slots = [(i, piece.index) for i, piece in enumerate(game.pieces) if piece is not None]
        trays = [self._draw_tray() for _ in range(TRAY_SAMPLES)]
        return plan_move(board, slots, trays)
