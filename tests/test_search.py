import os
import random
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from board import Board  # noqa: E402
from game import Game  # noqa: E402
from pieces import PIECE_POOL  # noqa: E402
from policies import build  # noqa: E402
from search import FEATURE_COUNT, PLACEMENTS, best_move, clear, features, occupancy  # noqa: E402


def _random_board(rng):
    board = Board()
    for _ in range(rng.randint(0, 40)):
        board.grid[rng.randrange(8)][rng.randrange(8)] = 1
    return board


def test_placements_match_board():
    rng = random.Random(1)
    for _ in range(200):
        board = _random_board(rng)
        occ = occupancy(board.grid)
        for pose, piece in enumerate(PIECE_POOL):
            expected = {(x, y) for y in range(8) for x in range(8) if board.can_place_piece(piece, x, y)}
            got = {(x, y) for x, y, mask in PLACEMENTS[pose] if not occ & mask}
            assert got == expected


def test_clear_matches_board():
    rng = random.Random(2)
    checked = 0
    for _ in range(300):
        board = _random_board(rng)
        occ = occupancy(board.grid)
        pose = rng.randrange(len(PIECE_POOL))
        options = [(x, y, mask) for x, y, mask in PLACEMENTS[pose] if not occ & mask]
        if not options:
            continue
        x, y, mask = rng.choice(options)
        after = board.copy()
        after.place_piece(PIECE_POOL[pose], x, y)
        rows, cols = after.check_full_lines()
        after.clear_lines(rows, cols)
        new_occ, lines = clear(occ | mask)
        assert new_occ == occupancy(after.grid)
        assert lines == len(rows) + len(cols)
        checked += lines > 0
    assert checked > 0


def test_features_have_fixed_length():
    values = features(0) + features((1 << 64) - 1)
    assert len(values) == 2 * FEATURE_COUNT
    assert all(isinstance(v, float) for v in values)


def test_default_policy_plays_legal_moves():
    policy = build(None)
    for seed in range(10):
        game = Game(seed=seed)
        policy.reset(seed)
        while not game.done and game.placements < 60:
            actions = game.available_actions()
            if not actions:
                break
            move = policy.act(game, actions)
            assert move in actions
            game.step(move)


def test_build_loads_weights_directory(tmp_path):
    np.savez(tmp_path / "value.npz", w=np.zeros(FEATURE_COUNT), b=np.array(0.5))
    policy = build(str(tmp_path))
    assert policy.name == "search"
    assert policy._bias == 0.5


def test_best_move_places_piece_when_full_tray_does_not_fit():
    grid = [[(x + y) % 2 == 0 for x in range(8)] for y in range(8)]
    single = next(i for i, p in enumerate(PIECE_POOL) if sum(map(sum, p.shape)) == 1)
    square = next(i for i, p in enumerate(PIECE_POOL)
                  if len(p.shape) == 2 and len(p.shape[0]) == 2 and sum(map(sum, p.shape)) == 4)
    move = best_move(occupancy(grid), [(0, square), (1, single)], lambda occ: 0.0, 12)
    assert move is not None and move[0] == 1
    assert (move[1] + move[2]) % 2 == 1
