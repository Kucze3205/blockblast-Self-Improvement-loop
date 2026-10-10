"""Spadek po współrzędnych ośmiu wag liścia na seedach treningowych; wynik to JSON dla --out."""
import argparse
import json
import os
import sys
from multiprocessing import Pool

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from game import Game
from search_policy import DEFAULT_WEIGHTS, SearchPolicy

CAP = 500
FACTORS = (1.25, 0.8)
MARGIN = 0.001


def play(job):
    seed, weights = job
    game = Game(seed)
    policy = SearchPolicy(weights)
    policy.reset(seed)
    while not game.done and game.placements < CAP:
        actions = game.available_actions()
        if not actions:
            break
        game.step(policy.act(game, actions))
    return min(game.placements, CAP)


def objective(pool, seeds, weights):
    lengths = pool.map(play, [(seed, weights) for seed in seeds])
    return sum(lengths) / (CAP * len(seeds))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--first-seed", type=int, default=1000)
    ap.add_argument("--seeds", type=int, default=64)
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--start", help="JSON z wagami startowymi zamiast domyślnych")
    ap.add_argument("--out", default=os.path.join(ROOT, "weights", "leaf.json"))
    args = ap.parse_args()

    seeds = list(range(args.first_seed, args.first_seed + args.seeds))
    best = dict(DEFAULT_WEIGHTS)
    if args.start:
        with open(args.start) as f:
            best.update(json.load(f))
    with Pool(args.workers) as pool:
        best_score = objective(pool, seeds, best)
        print(f"start {best_score:.4f}", flush=True)
        for rnd in range(args.rounds):
            improved = False
            for key in DEFAULT_WEIGHTS:
                for factor in FACTORS:
                    cand = dict(best)
                    cand[key] = best[key] * factor
                    score = objective(pool, seeds, cand)
                    print(f"round {rnd} {key}={cand[key]:.4g} score={score:.4f}", flush=True)
                    if score > best_score + MARGIN:
                        best, best_score = cand, score
                        improved = True
                        print("accept", json.dumps(best), flush=True)
                        break
            if not improved:
                break

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(best, f, indent=2)
    print(f"final {best_score:.4f} {json.dumps(best)}", flush=True)


if __name__ == "__main__":
    main()
