"""Trenuje weights/value.json: regresja grzbietowa czasu do przegranej, po rundach polityki."""
import argparse
import json
import os
from multiprocessing import Pool

import numpy as np

from game import Game
from policies import build
from search import features, occupancy

CAP = 500
HORIZON = 100
RIDGE = 1e-3
VALID_FRACTION = 0.2


def play(job):
    seed, weights = job
    policy = build(weights)
    policy.reset(seed)
    game = Game(seed=seed)
    states = []
    while not game.done and game.placements < CAP:
        actions = game.available_actions()
        if not actions:
            break
        states.append(features(occupancy(game.board.grid)))
        game.step(policy.act(game, actions))
    end = game.placements
    X = np.array(states, dtype=float).reshape(-1, len(features(0)))
    y = np.minimum(end - np.arange(len(states)), HORIZON).astype(float)
    return seed, X, y


def fit(X, y):
    A = np.hstack([X, np.ones((len(X), 1))])
    coef = np.linalg.solve(A.T @ A + RIDGE * np.eye(A.shape[1]), A.T @ y)
    return coef[:-1], float(coef[-1])


def r2(X, y, w, b):
    pred = X @ w + b
    return 1.0 - ((y - pred) ** 2).sum() / ((y - y.mean()) ** 2).sum()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--games", type=int, default=240)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--seed-base", type=int, default=50000)
    parser.add_argument("--out", default="weights")
    args = parser.parse_args()

    weights = None
    for rnd in range(args.rounds):
        first = args.seed_base + rnd * args.games
        seeds = list(range(first, first + args.games))
        with Pool(args.workers) as pool:
            results = pool.map(play, [(s, weights) for s in seeds], chunksize=4)
        results = [(X, y) for _, X, y in results if len(y)]

        cut = int(len(results) * (1 - VALID_FRACTION))
        X_train = np.vstack([X for X, _ in results[:cut]])
        y_train = np.concatenate([y for _, y in results[:cut]])
        X_valid = np.vstack([X for X, _ in results[cut:]])
        y_valid = np.concatenate([y for _, y in results[cut:]])
        w, b = fit(X_train, y_train)

        print(f"runda {rnd}: partie {len(results)}, stany {len(y_train)}+{len(y_valid)}, "
              f"R2 walidacja {r2(X_valid, y_valid, w, b):.3f}", flush=True)

        os.makedirs(args.out, exist_ok=True)
        with open(os.path.join(args.out, "value.json"), "w") as f:
            json.dump({"w": w.tolist(), "b": b}, f)
        weights = args.out


if __name__ == "__main__":
    main()
