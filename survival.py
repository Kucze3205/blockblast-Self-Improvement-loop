"""Polityka przeżycia na bitboardach: dokończalność tacki i dokładne ryzyko następnej tacki."""
import random

from pieces import PIECE_POOL, PIECE_TYPES

FULL = (1 << 64) - 1
ROW_MASKS = [0xFF << (8 * r) for r in range(8)]
COL_MASKS = [sum(1 << (8 * r + c) for r in range(8)) for c in range(8)]
WALL_MASKS = (COL_MASKS[0], COL_MASKS[7], ROW_MASKS[0], ROW_MASKS[7])
NOT_COL7 = FULL & ~COL_MASKS[7]

BEAM = 4
LEAF_TOP = 6
LINE_W = 6.0
EDGE_W = 1.0
HOLE_W = 8.0
DEAD_W = 300.0
Q_W = 40.0
NC_W = 200.0
SAMPLE_K = 32


def _pose_bits(shape):
    return sum(1 << (r * 8 + c) for r, row in enumerate(shape) for c, cell in enumerate(row) if cell)


POSE_BITS = [_pose_bits(piece.shape) for piece in PIECE_POOL]

POSE_PROB = [0.0] * len(PIECE_POOL)
for _poses in PIECE_TYPES:
    for _pose in _poses:
        POSE_PROB[_pose] = 1.0 / (len(PIECE_TYPES) * len(_poses))

PLACEMENT_XY = [
    [(x, y, POSE_BITS[pose] << (y * 8 + x))
     for y in range(8 - len(piece.shape) + 1)
     for x in range(8 - len(piece.shape[0]) + 1)]
    for pose, piece in enumerate(PIECE_POOL)
]
PLACEMENTS = [[mask for _, _, mask in poses] for poses in PLACEMENT_XY]

_TRAY_RNG = random.Random(0)
SAMPLE_TRAYS = [
    tuple(_TRAY_RNG.choices(range(len(POSE_PROB)), weights=POSE_PROB, k=3))
    for _ in range(SAMPLE_K)
]


def board_bits(grid):
    occ = 0
    for r, row in enumerate(grid):
        for c, cell in enumerate(row):
            if cell:
                occ |= 1 << (r * 8 + c)
    return occ


def clear_lines(occ):
    clear = 0
    lines = 0
    for mask in ROW_MASKS:
        if (occ & mask) == mask:
            clear |= mask
            lines += 1
    for mask in COL_MASKS:
        if (occ & mask) == mask:
            clear |= mask
            lines += 1
    return occ & ~clear, lines


def open_edges(occ):
    filled = bin(occ).count("1")
    adjacent = bin(occ & (occ >> 1) & NOT_COL7).count("1") + bin(occ & (occ >> 8)).count("1")
    walls = sum(bin(occ & mask).count("1") for mask in WALL_MASKS)
    return 4 * filled - 2 * adjacent - walls


def holes(occ):
    covered = occ
    for _ in range(7):
        covered |= (covered << 8) & FULL
    return bin(covered & ~occ).count("1")


def unplaceable_mass(occ):
    q = 0.0
    for pose, placements in enumerate(PLACEMENTS):
        for mask in placements:
            if not occ & mask:
                break
        else:
            q += POSE_PROB[pose]
    return q


def completable(occ, poses):
    if not poses:
        return True
    for j, pose in enumerate(poses):
        rest = poses[:j] + poses[j + 1:]
        for mask in PLACEMENTS[pose]:
            if occ & mask:
                continue
            after, _ = clear_lines(occ | mask)
            if completable(after, rest):
                return True
    return False


def _prescreen(lines, after):
    return LINE_W * lines - EDGE_W * open_edges(after) - HOLE_W * holes(after)


class SurvivalPolicy:
    name = "survival"

    def reset(self, game_seed):
        pass

    def act(self, game, actions):
        occ = board_bits(game.board.grid)
        slots = tuple((k, p.index) for k, p in enumerate(game.pieces) if p is not None)
        frontier = [(0, occ, None, slots)]
        leaves = []
        while frontier:
            children = []
            for lines, board, first, remaining in frontier:
                for pos, (k, pose) in enumerate(remaining):
                    rest = remaining[:pos] + remaining[pos + 1:]
                    for x, y, mask in PLACEMENT_XY[pose]:
                        if board & mask:
                            continue
                        after, cleared = clear_lines(board | mask)
                        root = first if first is not None else (k, x, y)
                        if rest:
                            children.append((lines + cleared, after, root, rest))
                        else:
                            leaves.append((lines + cleared, after, root))
            children.sort(key=lambda c: _prescreen(c[0], c[1]), reverse=True)
            frontier = []
            for child in children:
                if completable(child[1], tuple(pose for _, pose in child[3])):
                    frontier.append(child)
                    if len(frontier) == BEAM:
                        break

        if not leaves:
            return actions[0]
        leaves.sort(key=lambda c: _prescreen(c[0], c[1]), reverse=True)
        best_action, best_value = actions[0], None
        for lines, after, root in leaves[:LEAF_TOP]:
            q = unplaceable_mass(after)
            pnc = sum(not completable(after, tray) for tray in SAMPLE_TRAYS) / SAMPLE_K
            value = _prescreen(lines, after) - DEAD_W * q ** 3 - Q_W * q - NC_W * pnc
            if best_value is None or value > best_value:
                best_action, best_value = root, value
        return best_action
