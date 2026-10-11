"""Polityka przeżycia na bitboardach: dokończalność tacki i dokładne ryzyko następnej tacki."""
from pieces import PIECE_POOL, PIECE_TYPES

FULL = (1 << 64) - 1
ROW_MASKS = [0xFF << (8 * r) for r in range(8)]
COL_MASKS = [sum(1 << (8 * r + c) for r in range(8)) for c in range(8)]
WALL_MASKS = (COL_MASKS[0], COL_MASKS[7], ROW_MASKS[0], ROW_MASKS[7])
NOT_COL7 = FULL & ~COL_MASKS[7]

PRESCREEN = 8
LINE_W = 6.0
EDGE_W = 1.0
HOLE_W = 8.0
DEAD_W = 300.0
Q_W = 40.0


def _pose_bits(shape):
    return sum(1 << (r * 8 + c) for r, row in enumerate(shape) for c, cell in enumerate(row) if cell)


POSE_BITS = [_pose_bits(piece.shape) for piece in PIECE_POOL]

POSE_PROB = [0.0] * len(PIECE_POOL)
for _poses in PIECE_TYPES:
    for _pose in _poses:
        POSE_PROB[_pose] = 1.0 / (len(PIECE_TYPES) * len(_poses))

PLACEMENTS = [
    [POSE_BITS[pose] << (y * 8 + x)
     for y in range(8 - len(piece.shape) + 1)
     for x in range(8 - len(piece.shape[0]) + 1)]
    for pose, piece in enumerate(PIECE_POOL)
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


class SurvivalPolicy:
    name = "survival"

    def reset(self, game_seed):
        pass

    def act(self, game, actions):
        occ = board_bits(game.board.grid)
        ranked = []
        for action in actions:
            idx, x, y = action
            pose = game.pieces[idx].index
            after, lines = clear_lines(occ | (POSE_BITS[pose] << (y * 8 + x)))
            prescreen = LINE_W * lines - EDGE_W * open_edges(after) - HOLE_W * holes(after)
            ranked.append((prescreen, action, after))
        ranked.sort(key=lambda item: item[0], reverse=True)

        best_action, best_value = None, None
        evaluated = 0
        for prescreen, action, after in ranked:
            idx = action[0]
            rest = tuple(p.index for k, p in enumerate(game.pieces) if p is not None and k != idx)
            if not completable(after, rest):
                continue
            q = unplaceable_mass(after)
            value = prescreen - DEAD_W * q ** 3 - Q_W * q
            if best_value is None or value > best_value:
                best_action, best_value = action, value
            evaluated += 1
            if evaluated >= PRESCREEN:
                break
        if best_action is None:
            return ranked[0][1]
        return best_action
