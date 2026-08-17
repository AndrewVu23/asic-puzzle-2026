"""The checker's architecture, recovered from the extracted netlist.

`puzzle.gds` implements an 11x11 Star Battle validator. The 121 bits of `I` are the
grid in row-major order (column fastest); `success` asserts on the cycle after the
last cell if the placement is legal.

Everything here was derived by probing the extracted netlist, not assumed:
  - the 11-cycle period of the impulse response gives the grid width;
  - one bank of 22 flops (D fan-in 7 = 2 own bits + 4 column-counter bits + 1) holds
    a 2-bit count per column;
  - one bank of 22 flops (D fan-in 11 = 2 own + 4 column + 4 row + 1) holds a 2-bit
    count per region -- needing the row index is what makes a region a region;
  - the region map below is read off directly from which accumulator each cell
    perturbs;
  - 13 flops of D fan-in 3 form the 12-deep delay line that supplies the
    adjacency window (offsets 1, 10, 11, 12 = left, up-right, up, up-left);
  - 2-bit accumulators can only distinguish "exactly 2" from 0/1/3+, which fixes N=2.

Run:  python3 -m tools.starbattle
"""
from __future__ import annotations

if __package__ in (None, ""):        # allow `python3 tools/x.py` as well as `-m tools.x`
    import os as _os, sys as _sys
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))


def _p(*parts):
    """Path relative to the repo root, so the tools work from any cwd."""
    import os.path
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(here), *parts)

import collections
from itertools import combinations

W = 11
N = 2

REGIONS = [
    "IIIIICCHGGA",
    "IIKIICHHGGA",
    "IIKCCCCHHGA",
    "IIKCJJJAHHA",
    "KIKCJAAAAAA",
    "KKKCJJJAEEE",
    "CCCCCCJAEBB",
    "CDDDJJJAEBB",
    "CDDFAAAAEBB",
    "CCDFFAAAEEE",
    "CDDFAAAAAAA",
]

# region letter -> index of the flop holding bit 0 of that region's counter
REGION_FLOP = {"A": 26, "B": 27, "C": 28, "D": 29, "E": 69, "F": 70,
               "G": 71, "H": 72, "I": 73, "J": 77, "K": 78}
# column -> flop holding bit 0 of that column's counter
COLUMN_FLOP = [22, 6, 20, 11, 17, 2, 4, 7, 10, 8, 9]


def solve(n=N, limit=None):
    """Every legal placement: exactly n stars per row, column and region, none adjacent."""
    letters = sorted({ch for row in REGIONS for ch in row})
    rowsets = [cs for cs in combinations(range(W), n)
               if all(b - a > 1 for a, b in zip(cs, cs[1:]))]
    sols = []

    def rec(r, chosen, colcnt, regcnt):
        if limit and len(sols) >= limit:
            return
        if r == W:
            if all(v == n for v in colcnt) and all(regcnt[g] == n for g in letters):
                sols.append(list(chosen))
            return
        if any(colcnt[c] + (W - r) < n for c in range(W)):
            return
        for cs in rowsets:
            if chosen and any(abs(a - b) <= 1 for a in cs for b in chosen[-1]):
                continue
            if any(colcnt[c] + 1 > n for c in cs):
                continue
            for c in cs:
                colcnt[c] += 1
                regcnt[REGIONS[r][c]] += 1
            if all(regcnt[g] <= n for g in letters):
                chosen.append(cs)
                rec(r + 1, chosen, colcnt, regcnt)
                chosen.pop()
            for c in cs:
                colcnt[c] -= 1
                regcnt[REGIONS[r][c]] -= 1

    rec(0, [], [0] * W, collections.defaultdict(int))
    return sols


def stream(sol):
    """Row-major bit stream for a solution (list of per-row column tuples)."""
    return [1 if c in sol[r] else 0 for r in range(W) for c in range(W)]


def play(bits, tail=240, reset=4):
    """Drive the extracted netlist. -> (O bytes per cycle, success per cycle)."""
    from tools.netlist import Netlist
    from tools.sim import Sim
    nl = Netlist(_p("puzzle.gds"), ["clk", "rst_n", "enable", "I"],
                 [f"O[{i}]" for i in range(8)] + ["success"])
    sim = Sim(nl)
    for _ in range(reset):
        sim.cycle(sim.make_inputs(rst_n=0, enable=0, I=0))
    out, succ = [], []
    for b in list(bits) + [0] * tail:
        sim.cycle(sim.make_inputs(rst_n=1, enable=1, I=b))
        out.append(sum((1 if sim.port(f"O[{i}]") else 0) << i for i in range(8)))
        succ.append(sim.port("success"))
    return out, succ


def main():
    sols = solve()
    print(f"legal placements for N={N}: {len(sols)}")
    sol = sols[0]
    for r in range(W):
        print("   ", " ".join("*" if c in sol[r] else "." for c in range(W)),
              "  ", REGIONS[r])
    bits = stream(sol)
    out, succ = play(bits)
    text = "".join(chr(o) for o in out if o)
    print(f"\nstars={sum(bits)}  success={any(succ)} "
          f"(first at cycle {succ.index(True) if any(succ) else None})")
    print(f"O decodes to: {text!r}")
    assert any(succ) and text == "(* TWO STARS *)"
    print("OK")


if __name__ == "__main__":
    main()
