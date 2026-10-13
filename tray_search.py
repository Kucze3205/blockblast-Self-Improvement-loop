"""
Wiązka po sekwencjach klocków tacki z ryzykiem następnej tacki, na bitboardach.
"""
import random

from bitboard import BORDER, FULL, NOT_COL0, NOT_COL7, PLACEMENTS, board_to_bits, place_and_clear
from pieces import PIECE_TYPES

BEAM = 40
FINALISTS = 8
FINALISTS_ENDGAME = 20
ENDGAME_FREE = 22
SAMPLES = 256
LINE_W = 4.2
OCC_W = 1.4
ISO_W = 0.75
TRANS_W = 1.5
EDGE_W = 2.0
DEAD_W = 12.3
DEATH_W = 400.0
FIT_W = 80.0
PIECES_PER_TRAY = 3
INSIDE_VERTICAL = (1 << 56) - 1


def _fits(bits, pose):
    for _, _, mask in PLACEMENTS[pose]:
        if not bits & mask:
            return True
    return False


def _leaf(bits, lines):
    empty = FULL ^ bits
    touching = ((empty << 1) & NOT_COL0) | ((empty >> 1) & NOT_COL7) | (empty << 8) | (empty >> 8)
    isolated = (empty & ~touching).bit_count()
    transitions = (((bits ^ (bits >> 1)) & NOT_COL7).bit_count()
                   + ((bits ^ (bits >> 8)) & INSIDE_VERTICAL).bit_count())
    return (LINE_W * lines - OCC_W * bits.bit_count() - ISO_W * isolated
            - TRANS_W * transitions - EDGE_W * (BORDER & empty).bit_count())


def _completable(bits, poses):
    if not poses:
        return True
    for k, pose in enumerate(poses):
        left = poses[:k] + poses[k + 1:]
        for _, _, mask in PLACEMENTS[pose]:
            if not bits & mask:
                nxt, _ = place_and_clear(bits, mask)
                if _completable(nxt, left):
                    return True
    return False


def _next_piece_stats(bits):
    q_sum = 0.0
    dead = 0
    for poses in PIECE_TYPES:
        fitting = sum(_fits(bits, p) for p in poses)
        q_sum += fitting / len(poses)
        dead += fitting == 0
    return q_sum / len(PIECE_TYPES), dead


def _tray_value(bits, lines, samples):
    q, dead = _next_piece_stats(bits)
    stuck = 0
    for poses in samples:
        if any(_fits(bits, p) for p in poses) and not _completable(bits, poses):
            stuck += 1
    death = (1.0 - q) ** PIECES_PER_TRAY + stuck / len(samples)
    return _leaf(bits, lines) - DEAD_W * dead - DEATH_W * death - FIT_W * (1.0 - q)


def _draw_samples(key):
    rng = random.Random(key)
    return [tuple(rng.choice(rng.choice(PIECE_TYPES)) for _ in range(PIECES_PER_TRAY))
            for _ in range(SAMPLES)]


def _finals(bits, pending):
    frontier = [(bits, pending, None, 0)]
    finals = {}
    while frontier:
        children = {}
        for board, left_pieces, root, lines_so_far in frontier:
            for k, (idx, pose) in enumerate(left_pieces):
                rest = left_pieces[:k] + left_pieces[k + 1:]
                for x, y, mask in PLACEMENTS[pose]:
                    if board & mask:
                        continue
                    nxt, lines = place_and_clear(board, mask)
                    total = lines_so_far + lines
                    value = _leaf(nxt, total)
                    first = root if root is not None else (idx, x, y)
                    if rest:
                        state = (nxt, rest)
                        if state not in children or value > children[state][0]:
                            children[state] = (value, nxt, rest, first, total)
                    elif nxt not in finals or value > finals[nxt][0]:
                        finals[nxt] = (value, first, total)
        frontier = []
        for _, nxt, rest, first, total in sorted(children.values(), key=lambda c: -c[0]):
            if len(frontier) == BEAM:
                break
            if any(_fits(nxt, p) for _, p in rest):
                frontier.append((nxt, rest, first, total))
    return finals


def _pool(finals, size):
    ranked = sorted(finals.items(), key=lambda kv: -kv[1][0])
    pool = dict(ranked[:size])
    best_per_lines = {}
    for board, entry in ranked:
        best_per_lines.setdefault(entry[2], (board, entry))
    pool.update(best_per_lines.values())
    return pool


def _search(bits, pending, samples):
    finals = _finals(bits, pending)
    if not finals:
        return None
    endgame = (FULL ^ bits).bit_count() <= ENDGAME_FREE
    best_value, best_action = None, None
    for board, (_, first, lines) in _pool(finals, FINALISTS_ENDGAME if endgame else FINALISTS).items():
        value = _tray_value(board, lines, samples)
        if best_value is None or value > best_value:
            best_value, best_action = value, first
    return best_action


class TraySearchPolicy:
    name = "tray_search"

    def reset(self, game_seed):
        self._game_seed = game_seed

    def act(self, game, actions):
        bits = board_to_bits(game.board.grid)
        pending = tuple((i, piece.index) for i, piece in enumerate(game.pieces) if piece is not None)
        samples = _draw_samples(f"{self._game_seed}:{game.placements}")
        action = _search(bits, pending, samples)
        return action if action is not None else actions[0]
