"""Jednorazowe przeliczenie starych drzew bieżącym ewaluatorem (#48): lista węzłów do oceny i węzły do wznowienia.

  przelicz.py lista <drzewo>...   "<drzewo> <węzeł> <sha>" dla ocenionych węzłów bez oceny bieżącym ewaluatorem
  przelicz.py wznow               "<drzewo> <węzeł> <kolejność>" dla węzłów otwartych drzew bez działającej sesji

Ocena bieżącym ewaluatorem dopisuje drugi hash do `oceny.s_sym` (hash zależy od parametrów i rozdań drzewa), a `s_v`
bierze ostatni wpis. Awaryjnie: ocena z limitem `cap` i ponad 300 rozdaniami też jest bieżąca.
"""
import json
import os
import sys

CFG = json.load(open(os.path.join(".github", "evaluator", "config.json"), encoding="utf-8"))
TREES = "trees"


def rekordy(t):
    d = os.path.join(TREES, str(t))
    for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if f.endswith(".json"):
            with open(os.path.join(d, f), encoding="utf-8") as fh:
                yield f[:-5], json.load(fh)


def biezaca(r):
    o = r.get("oceny") or {}
    if len(o.get("s_sym") or {}) >= 2:
        return True
    v = list((o.get("sym") or {}).values())
    if not v or not v[-1].get("przezycie"):
        return False
    return max(v[-1]["przezycie"]) <= CFG["cap"] and len(v[-1]["przezycie"]) > 300


def lista(drzewa):
    for t in drzewa:
        for n, r in sorted(rekordy(t), key=lambda kv: kv[1]["kolejnosc"]):
            if r.get("stan") == "oceniony" and not biezaca(r):
                print(t, n, r["sha"])


def wznow():
    nums = sorted(int(f[:-5]) for f in os.listdir(TREES) if f.endswith(".json") and f[:-5].isdigit())
    for t in nums:
        with open(os.path.join(TREES, "%d.json" % t), encoding="utf-8") as fh:
            if json.load(fh).get("koniec"):
                continue
        for n, r in sorted(rekordy(t), key=lambda kv: kv[1]["kolejnosc"]):
            if r.get("stan") in ("sesja", "zaparkowany"):
                print(t, n, r["kolejnosc"])


if __name__ == "__main__":
    {"lista": lambda: lista(sys.argv[2:]), "wznow": wznow}[sys.argv[1]]()
