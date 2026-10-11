"""Trening wag n-krotek metodą TD(0) na partiach własnej gry (ε-zachłanna polityka)."""
import argparse
import json
import os
import random
import sys
import time
from multiprocessing import Pool

import valuation
from game import Game
from policies import EVAL_BEAM, NTuplePolicy

CAP = 500


def play(job):
    table, seed, epsilon = job
    rng = random.Random(seed)
    policy = NTuplePolicy(table, beam=EVAL_BEAM)
    game = Game(seed=seed)
    visited = []
    while not game.done and game.placements < CAP:
        actions = game.available_actions()
        if not actions:
            break
        if rng.random() < epsilon:
            action = policy.explore(game, actions, rng)
        else:
            action = policy.act(game, actions)
        game.step(action)
        visited.append(valuation.occupancy(game.board.grid))
    return visited, game.placements


def save(path, table):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(valuation.dump_table(table), fh)
    os.replace(tmp, path)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Trening wag n-krotek (Monte Carlo)")
    parser.add_argument("--out", default="weights/ntuple.json")
    parser.add_argument("--minutes", type=float, default=60.0)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--epsilon", type=float, default=0.05)
    parser.add_argument("--alpha", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--save-every", type=int, default=200)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)

    table = [0.0] * valuation.TABLE_SIZE
    if args.resume and os.path.exists(args.out):
        with open(args.out, encoding="utf-8") as fh:
            table = valuation.load_table(json.load(fh))
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)

    rng = random.Random(args.seed)
    deadline = time.time() + args.minutes * 60
    started = time.time()
    episodes, bucket, recent = 0, 0, []
    with Pool(args.workers) as pool:
        while time.time() < deadline:
            jobs = [
                (table, rng.randrange(1, 2**31 - 1), args.epsilon)
                for _ in range(args.workers)
            ]
            for visited, length in pool.map(play, jobs):
                for t, occ in enumerate(visited):
                    if t + 1 < len(visited):
                        target = 1 / CAP + valuation.value(table, visited[t + 1])
                    else:
                        target = 0.0
                    valuation.learn(table, occ, target, args.alpha)
                episodes += 1
                recent.append(length)
            if episodes // args.save_every != bucket:
                bucket = episodes // args.save_every
                save(args.out, table)
                tail = recent[-100:]
                print(
                    "episodes={0} mean_len_last100={1:.1f} elapsed_s={2:.0f}".format(
                        episodes, sum(tail) / len(tail), time.time() - started
                    ),
                    flush=True,
                )
    save(args.out, table)
    print("done episodes={0}".format(episodes), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
