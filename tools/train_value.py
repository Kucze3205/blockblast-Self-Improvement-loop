"""Dopasowuje liść do skutków: logistyczna P(przegrana w najbliższych H tackach | składniki liścia).

Dane: partie polityki bazowej (search bez wag), podział po seedzie (co TEST_EVERY-ty seed to test).
Zapis: weights/value.json. AUC na zbiorze testowym to proxy, nie wynik oceny.

    python3 tools/train_value.py [partie] [limit tacek] [H]
"""
import json
import os
import sys
from multiprocessing import Pool

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from game import Game  # noqa: E402
import survival as S  # noqa: E402

GAMES = int(sys.argv[1]) if len(sys.argv) > 1 else 400
CAP = int(sys.argv[2]) if len(sys.argv) > 2 else 400
H = int(sys.argv[3]) if len(sys.argv) > 3 else 10
SEED0 = 5000
TEST_EVERY = 5


def play(seed):
    g = Game(seed=seed)
    pol = S.SearchPolicy()
    pol.reset(seed)
    boards, lines = [], []
    acc = 0
    while len(boards) < CAP and not g.done:
        acts = g.available_actions()
        if not acts:
            break
        if g.round_placement == 0:
            boards.append(S.board_bits(g))
            lines.append(acc)
            acc = 0
        g.step(pol.act(g, acts))
        acc += g.last_lines_cleared
    return seed, boards, lines, g.done or not g.available_actions()


def labelled(seed, boards, lines, died):
    n = len(boards)
    out = []
    for t, (b, ln) in enumerate(zip(boards, lines)):
        if died:
            y = 1 if n - 1 - t < H else 0
        elif t + H <= n:
            y = 0
        else:
            continue
        out.append((seed, t, b, ln, y))
    return out


def components(row):
    seed, t, board, ln, _y = row
    pol = S.SearchPolicy()
    pol.reset(seed * 100003 + t)
    trays = pol._hard_trays()
    hard = sum(not S._playable(board, tr) for tr in trays) / len(trays)
    mean_fit, dead = S._fit_stats(board)
    cheap = S._cheap(board)
    risk = (1.0 - mean_fit) ** 3
    hand = (-S.P["hard"] * hard + cheap + S.P["line"] * ln - S.P["risk"] * risk
            - S.P["fit"] * (1.0 - mean_fit) - S.P["dead"] * dead)
    return [hard, risk, mean_fit, dead, cheap, ln], hand


def auc(score, y):
    order = np.argsort(score, kind="mergesort")
    ranks = np.empty(len(score))
    ranks[order] = np.arange(1, len(score) + 1)
    pos = y == 1
    n1, n0 = pos.sum(), (~pos).sum()
    return (ranks[pos].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)


def fit(X, y, lam=1e-2, iters=50):
    Xb = np.hstack([X, np.ones((len(X), 1))])
    theta = np.zeros(Xb.shape[1])
    R = lam * np.eye(Xb.shape[1])
    R[-1, -1] = 0.0
    for _ in range(iters):
        p = 1.0 / (1.0 + np.exp(-np.clip(Xb @ theta, -30, 30)))
        g = Xb.T @ (p - y) + R @ theta
        Hm = (Xb * (p * (1 - p))[:, None]).T @ Xb + R
        step = np.linalg.solve(Hm, g)
        theta -= step
        if np.abs(step).max() < 1e-8:
            break
    return theta[:-1], float(theta[-1])


if __name__ == "__main__":
    seeds = list(range(SEED0, SEED0 + GAMES))
    with Pool(4) as pool:
        runs = pool.map(play, seeds, chunksize=1)
        rows = []
        for seed, boards, lines, died in runs:
            rows.extend(labelled(seed, boards, lines, died))
        parts = pool.map(components, rows, chunksize=512)
    deaths = sum(1 for r in runs if r[3])
    y = np.array([r[4] for r in rows], dtype=float)
    seed_of = np.array([r[0] for r in rows])
    print("partie", len(runs), "smierci", deaths, "stany", len(rows),
          "odsetek dodatnich", round(float(y.mean()), 4), flush=True)

    X = np.array([p[0] for p in parts], dtype=float)
    hand = np.array([p[1] for p in parts], dtype=float)
    test = (seed_of - SEED0) % TEST_EVERY == 0
    mu = X[~test].mean(axis=0)
    sd = X[~test].std(axis=0)
    sd = np.where(sd < 1e-9, 1.0, sd)
    Z = (X - mu) / sd
    w, b = fit(Z[~test], y[~test])
    auc_fit = auc(Z[test] @ w + b, y[test])
    auc_hand = auc(-hand[test], y[test])
    print("AUC test: lisc reczny", round(float(auc_hand), 4),
          "| logistyczna na skutkach", round(float(auc_fit), 4), flush=True)

    out = {
        "features": list(S.FEATURES), "mu": mu.tolist(), "sd": sd.tolist(),
        "w": w.tolist(), "b": b, "horizon": H, "cap": CAP, "games": GAMES,
        "states": len(rows), "auc_test_hand": float(auc_hand), "auc_test_fit": float(auc_fit),
    }
    os.makedirs(os.path.join(ROOT, "weights"), exist_ok=True)
    with open(os.path.join(ROOT, "weights", "value.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("zapisano weights/value.json", dict(zip(S.FEATURES, np.round(w, 3).tolist())), round(b, 3))
