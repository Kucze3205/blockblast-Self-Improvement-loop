import random
import unittest
from types import SimpleNamespace

from board import Board
from game import Game
from pieces import PIECE_POOL
from policies import _POSITIONS, _bits, _layable, _leaf, _mask, _place, _single, build


class PlacementMatchesBoardTest(unittest.TestCase):
    def test_random_placements_match_board(self):
        rng = random.Random(7)
        checked = 0
        for _ in range(400):
            board = Board()
            for r in range(8):
                for c in range(8):
                    board.grid[r][c] = 1 if rng.random() < 0.6 else 0
            piece = rng.choice(PIECE_POOL)
            spots = [
                (x, y)
                for y in range(9 - len(piece.shape))
                for x in range(9 - len(piece.shape[0]))
                if board.can_place_piece(piece, x, y)
            ]
            if not spots:
                continue
            x, y = rng.choice(spots)
            expected = board.copy()
            expected.place_piece(piece, x, y)
            rows, cols = expected.check_full_lines()
            expected.clear_lines(rows, cols)
            bits, lines = _place(_bits(board.grid), _mask(piece.index, x, y))
            self.assertEqual(bits, _bits(expected.grid))
            self.assertEqual(lines, len(rows) + len(cols))
            checked += 1
        self.assertGreater(checked, 100)


class PolicyPlaysLegalMovesTest(unittest.TestCase):
    def test_moves_are_legal_and_deterministic(self):
        for seed in range(3):
            histories = []
            for _ in range(2):
                policy = build(None)
                game = Game(seed)
                policy.reset(seed)
                history = []
                for _ in range(40):
                    actions = game.available_actions()
                    if game.done or not actions:
                        break
                    move = policy.act(game, actions)
                    self.assertIn(move, actions)
                    history.append(move)
                    _, _, done, message = game.step(move)
                    self.assertNotEqual(message, "wrong_placement")
                    if done:
                        break
                histories.append(history)
            self.assertEqual(histories[0], histories[1])


def _engine_layable(board, pieces):
    if not pieces:
        return True
    for i, piece in enumerate(pieces):
        rest = pieces[:i] + pieces[i + 1:]
        for y in range(9 - len(piece.shape)):
            for x in range(9 - len(piece.shape[0])):
                if board.can_place_piece(piece, x, y):
                    nxt = board.copy()
                    nxt.place_piece(piece, x, y)
                    rows, cols = nxt.check_full_lines()
                    nxt.clear_lines(rows, cols)
                    if _engine_layable(nxt, rest):
                        return True
    return False


class LayableMatchesEngineTest(unittest.TestCase):
    def test_layable_matches_engine_search(self):
        rng = random.Random(11)
        outcomes = []
        for _ in range(120):
            board = Board()
            fill = rng.uniform(0.2, 0.8)
            for r in range(8):
                for c in range(8):
                    board.grid[r][c] = 1 if rng.random() < fill else 0
            poses = tuple(sorted(rng.randrange(len(PIECE_POOL)) for _ in range(3)))
            expected = _engine_layable(board, [PIECE_POOL[p] for p in poses])
            self.assertEqual(_layable(_bits(board.grid), poses, {}), expected)
            outcomes.append(expected)
        self.assertGreater(sum(outcomes), 10)
        self.assertGreater(len(outcomes) - sum(outcomes), 10)


class SingleKeepsTrayLayableTest(unittest.TestCase):
    def test_single_prefers_moves_that_keep_rest_layable(self):
        rng = random.Random(23)
        forced = 0
        for _ in range(200):
            fill = rng.uniform(0.4, 0.8)
            board = Board()
            for r in range(8):
                for c in range(8):
                    board.grid[r][c] = 1 if rng.random() < fill else 0
            bits = _bits(board.grid)
            pieces = [SimpleNamespace(index=rng.randrange(len(PIECE_POOL))) for _ in range(3)]
            game = SimpleNamespace(pieces=pieces)
            actions = [
                (i, x, y)
                for i, piece in enumerate(pieces)
                for x, y, m in _POSITIONS[piece.index]
                if not bits & m
            ]
            memo = {}
            outcomes = {}
            for idx, x, y in actions:
                nb, cleared = _place(bits, _mask(pieces[idx].index, x, y))
                rest = tuple(sorted(p.index for j, p in enumerate(pieces) if j != idx))
                outcomes[(idx, x, y)] = (_layable(nb, rest, memo), _leaf(nb, cleared))
            if not any(ok for ok, _ in outcomes.values()):
                continue
            self.assertTrue(outcomes[_single(bits, game, actions)][0])
            if not max(outcomes.values(), key=lambda o: o[1])[0]:
                forced += 1
        self.assertGreater(forced, 5)


if __name__ == "__main__":
    unittest.main()
