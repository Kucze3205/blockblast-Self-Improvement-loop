import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import policies
from game import Game


class TestTrayBeamPolicy(unittest.TestCase):
    def test_build_returns_policy_that_ignores_weights(self):
        game = Game(seed=1)
        actions = game.available_actions()
        for weights in (None, "nieistniejacy/katalog"):
            policy = policies.build(weights)
            policy.reset(0)
            self.assertIn(policy.act(game, actions), actions)

    def test_moves_are_legal_over_short_games(self):
        for seed in range(3):
            policy = policies.build(None)
            policy.reset(seed)
            game = Game(seed=seed)
            for _ in range(60):
                actions = game.available_actions()
                if game.done or not actions:
                    break
                move = policy.act(game, actions)
                self.assertIn(move, actions)
                _, _, _, reason = game.step(move)
                self.assertNotEqual(reason, "wrong_placement")


if __name__ == "__main__":
    unittest.main(verbosity=2)
