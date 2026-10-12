"""Polityka drzewa: którą paczkę węzłów otworzyć w następnej rundzie.

Deterministyczna: bez losowania, bez czasu, bez niczego poza `question`.
`solve(question)` zwraca listę akcji: `None` otwiera nowy łańcuch od korzenia,
nazwa liścia (`"2.3"`) kontynuuje jego łańcuch. Pusta lista kończy drzewo.

Widok `question`: `max_parallelism` (W), `max_rounds` (K), `round` (ukończone rundy),
`baseline_score`, `observed()` (ocenione węzły: `wezel`, `lancuch`, `glebokosc`, `rodzic`,
`s_v`, `delta` względem rodzica) i `legal_actions()`. Maszyneria odrzuca akcje niedozwolone
i obcina paczkę do W, więc polityka nie musi pilnować kontraktu.
"""
MISSES = 2   # tyle kolejnych węzłów bez poprawy względem rodzica zamyka łańcuch


def solve(question):
    obs = question.observed()
    if not obs:
        return [None] * question.max_parallelism
    chains = {}
    for o in obs:
        chains.setdefault(o["lancuch"], []).append(o)
    packet = []
    for nodes in chains.values():
        if len(nodes) >= MISSES and all(o["delta"] <= 0 for o in nodes[-MISSES:]):
            continue
        packet.append(nodes[-1]["wezel"])
    return packet[:question.max_parallelism]
