"""Polityka drzewa: którą paczkę węzłów otworzyć w następnej rundzie.

Deterministyczna: bez losowania, bez czasu, bez niczego poza `question`.
`solve(question)` zwraca listę akcji: `None` otwiera nowy łańcuch od korzenia,
nazwa liścia (`"2.3"`) kontynuuje jego łańcuch. Pusta lista kończy drzewo.

Widok `question`: `max_parallelism` (W), `max_rounds` (K), `round` (ukończone rundy),
`baseline_score`, `observed()` (ocenione węzły: `wezel`, `lancuch`, `glebokosc`, `rodzic`,
`s_v`, `delta` względem rodzica) i `legal_actions()`. Maszyneria odrzuca akcje niedozwolone
i obcina paczkę do W, więc polityka nie musi pilnować kontraktu.

Struktura decyzji: czas jest tani (beta * godziny), a paczka kosztuje tyle co jej najdłuższy
węzeł, więc wolne miejsca w paczce są prawie darmowe. Dlatego łańcuch zamykamy dopiero, gdy
stoi w miejscu (kilka ostatnich węzłów nie przebiło jego własnego rekordu) i wyraźnie
przegrywa z liderem; zwolnione miejsca idą na nowe łańcuchy, o ile zostało dość rund, by
nowy łańcuch zdążył dojrzeć. Pojedynczy spadek niczego nie zamyka.
"""
STALL = 3          # tyle ostatnich węzłów bez nowego rekordu łańcucha oznacza zastój
EPS = 0.005        # o tyle trzeba przebić rekord łańcucha, żeby to była poprawa
GAP = 0.02         # tyle za liderem musi być zastojowy łańcuch, żeby go zamknąć
FRESH_ROUNDS = 4   # nowy łańcuch ma sens, gdy zostało co najmniej tyle rund


def _stalled(nodes):
    if len(nodes) <= STALL:
        return False
    best_before = max(o["s_v"] for o in nodes[:-STALL])
    recent_best = max(o["s_v"] for o in nodes[-STALL:])
    return recent_best < best_before + EPS


def solve(question):
    W = question.max_parallelism
    obs = question.observed()
    if not obs:
        return [None] * W
    legal_all = question.legal_actions()
    legal = set(a for a in legal_all if a is not None)
    can_open = None in legal_all

    chains = {}
    for o in obs:
        chains.setdefault(o["lancuch"], []).append(o)
    leader = max(o["s_v"] for o in obs)

    live = []
    for nodes in chains.values():
        tip = nodes[-1]["wezel"]
        if tip not in legal:
            continue
        best = max(o["s_v"] for o in nodes)
        if _stalled(nodes) and best < leader - GAP:
            continue
        live.append((-best, -nodes[-1]["s_v"], tip))
    live.sort()
    packet = [t[2] for t in live][:W]

    remaining = question.max_rounds - question.round
    if can_open and remaining >= FRESH_ROUNDS:
        packet += [None] * (W - len(packet))
    return packet[:W]
