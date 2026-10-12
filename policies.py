"""
Polityki grające, których używa benchmark.

Wszystkie są deterministyczne przy zadanym seedzie partii — benchmark mierzy,
co polityka umie, a nie jak wypada w trakcie nauki (#8).
"""
import random

import bitboard
from board import Board
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


MOBILITY_WEIGHT = 1e-5


def build(weights):
    """Polityka nie używa wag; argument zostaje ze względu na kontrakt oceny."""
    return TrayBeamPolicy()


class TrayBeamPolicy:
    """Wiązka po tacce na maskach bitowych. Ruch oceniany szansą, że losowy klocek zmieści się po tacce."""

    WIDTHS = (4, 3)

    def reset(self, game_seed):
        pass

    def act(self, game, actions):
        pieces = game.pieces
        occupied = bitboard.occupancy(game.board.grid)
        states = []
        for action in actions:
            idx, x, y = action
            child, _ = bitboard.place(occupied, pieces[idx].index, x, y)
            rest = tuple(p.index for j, p in enumerate(pieces) if p is not None and j != idx)
            states.append((action, child, rest))

        best_action, best_rank, depth = None, None, 0
        while states:
            open_states = []
            for action, occ, rest in states:
                masks = bitboard.fit_masks(occ)
                fit, mobility = bitboard.fit_stats(masks)
                rank = fit + MOBILITY_WEIGHT * mobility
                if not rest:
                    if best_rank is None or rank > best_rank:
                        best_action, best_rank = action, rank
                elif any(masks[p] for p in rest):
                    open_states.append((rank, action, occ, rest, masks))
            open_states.sort(key=lambda s: s[0], reverse=True)
            width = self.WIDTHS[depth] if depth < len(self.WIDTHS) else len(open_states)
            states = []
            for _, action, occ, rest, masks in open_states[:width]:
                for pose in set(rest):
                    remaining = list(rest)
                    remaining.remove(pose)
                    mask = masks[pose]
                    while mask:
                        low = mask & -mask
                        bit = low.bit_length() - 1
                        child, _ = bitboard.place(occ, pose, bit % bitboard.SIZE, bit // bitboard.SIZE)
                        states.append((action, child, tuple(remaining)))
                        mask ^= low
            depth += 1
        if best_action is None:
            return _survive_longest(pieces, occupied, actions)
        return best_action


def _placements_left(occupied, rest):
    if not rest:
        return 0
    masks = bitboard.fit_masks(occupied)
    if len(rest) == 1:
        return 1 if masks[rest[0]] else 0
    best = 0
    for pose in set(rest):
        remaining = list(rest)
        remaining.remove(pose)
        mask = masks[pose]
        while mask:
            low = mask & -mask
            bit = low.bit_length() - 1
            child, _ = bitboard.place(occupied, pose, bit % bitboard.SIZE, bit // bitboard.SIZE)
            best = max(best, 1 + _placements_left(child, tuple(remaining)))
            if best == len(rest):
                return best
            mask ^= low
    return best


def _survive_longest(pieces, occupied, actions):
    best_action, best_key = None, None
    for action in actions:
        idx, x, y = action
        child, _ = bitboard.place(occupied, pieces[idx].index, x, y)
        rest = tuple(p.index for j, p in enumerate(pieces) if p is not None and j != idx)
        fit, _ = bitboard.fit_stats(bitboard.fit_masks(child))
        key = (1 + _placements_left(child, rest), fit)
        if best_key is None or key > best_key:
            best_action, best_key = action, key
    return best_action
