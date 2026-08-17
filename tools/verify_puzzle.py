"""End-to-end verification of the Star Battle conclusion.

  python3 -m tools.verify_puzzle           # ~2 min
  python3 -m tools.verify_puzzle --full    # ~20 min, exhaustive relocation sweep

Checks, in order: the extraction still replays the vendor waveform; the recovered
region map is a well-formed partition; the puzzle has a unique N=2 solution and the
chip accepts it; a large family of near-misses is rejected, including cases that
isolate each of the three rules; and the protocol edges behave.
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

import collections, random, sys

from tools.netlist import Netlist, OUTPUT_PINS
from tools.sim import Sim
from tools import vcd
from tools.starbattle import REGIONS, W, solve, stream

IN = ["clk", "rst_n", "enable", "I"]
OUT = [f"O[{i}]" for i in range(8)] + ["success"]
LETTERS = sorted({ch for row in REGIONS for ch in row})

_fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"   -- {detail}" if detail else ""))
    if not cond:
        _fails.append(name)


def main(full=False):
    nl = Netlist(_p("puzzle.gds"), IN, OUT)
    sim = Sim(nl)

    def play(bits, tail=40, enable=1, reset=4):
        sim.reset_state()
        for _ in range(reset):
            sim.cycle(sim.make_inputs(rst_n=0, enable=0, I=0))
        out, succ = [], []
        for b in list(bits) + [0] * tail:
            sim.cycle(sim.make_inputs(rst_n=1, enable=enable, I=b))
            out.append(sum((1 if sim.port(f"O[{i}]") else 0) << i for i in range(8)))
            succ.append(sim.port("success"))
        return out, succ

    def accepts(grid):
        return any(play([grid[r][c] for r in range(W) for c in range(W)], tail=3)[1])

    print("\n== A. Extraction still matches the vendor waveform ==")
    _, _, tl = vcd.timeline(_p("example_inputs.vcd"))
    prev, edges = None, []
    for _t, h in tl:
        if prev == "0" and h.get("clk") == "1":
            edges.append(h)
        prev = h.get("clk")
    sim.reset_state()
    mism = cmp_cycles = 0
    for h in edges:
        sim.cycle(sim.make_inputs(rst_n=int(h["rst_n"]), enable=int(h["enable"]), I=int(h["I"])))
        got = (sum((1 if sim.port(f"O[{i}]") else 0) << i for i in range(8)),
               1 if sim.port("success") else 0)
        ro, rs = h.get("O"), h.get("success")
        if ro and set(ro) <= set("01") and rs in ("0", "1"):
            cmp_cycles += 1
            mism += got != (int(ro, 2), int(rs))
    check(f"vendor VCD replay ({cmp_cycles} cycles)", mism == 0 and cmp_cycles >= 300,
          f"{mism} mismatches")

    print("\n== B. Region map is a well-formed partition ==")
    cells = [(r, c) for r in range(W) for c in range(W)]
    sizes = collections.Counter(REGIONS[r][c] for r, c in cells)
    check("121 cells across 11 regions", len(cells) == 121 and len(sizes) == 11,
          str(dict(sorted(sizes.items()))))

    def connected(g):
        ms = {(r, c) for r, c in cells if REGIONS[r][c] == g}
        seen = {next(iter(ms))}
        st = list(seen)
        while st:
            r, c = st.pop()
            for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                p = (r + dr, c + dc)
                if p in ms and p not in seen:
                    seen.add(p)
                    st.append(p)
        return seen == ms
    check("every region is edge-connected", all(connected(g) for g in sizes))

    print("\n== C. The solution ==")
    sols = solve()
    check("exactly one legal placement at N=2", len(sols) == 1)
    check("no legal placement at N=3", len(solve(3)) == 0)
    check("N=1 is under-constrained", len(solve(1)) > 1, f"{len(solve(1))} placements")
    sol = sols[0]
    bits = stream(sol)
    out, succ = play(bits)
    check("chip accepts it", any(succ),
          f"success first at cycle {succ.index(True) if any(succ) else None}")
    check("success asserts one cycle after the 121st bit", succ and succ.index(True) == 121)
    check("success stays latched", all(succ[succ.index(True):]))
    check("O decodes to '(* TWO STARS *)'",
          "".join(chr(o) for o in out if o) == "(* TWO STARS *)")

    print("\n== D. Near-misses must be rejected ==")
    grid = [[1 if c in sol[r] else 0 for c in range(W)] for r in range(W)]
    stars = [(r, c) for r in range(W) for c in range(W) if grid[r][c]]
    free = [(r, c) for r, c in cells if not grid[r][c]]

    def regs_ok(g):
        rc = collections.Counter(REGIONS[r][c] for r, c in cells if g[r][c])
        return all(rc[l] == 2 for l in LETTERS)

    def adj_ok(g):
        st = [(r, c) for r, c in cells if g[r][c]]
        return not any(a < b and abs(a[0] - b[0]) <= 1 and abs(a[1] - b[1]) <= 1
                       for a in st for b in st)

    moves = [(s, f) for s in stars for f in free]
    if not full:
        random.seed(0)
        moves = random.sample(moves, 200)
    bad = 0
    for (r, c), (r2, c2) in moves:
        g = [row[:] for row in grid]
        g[r][c] = 0
        g[r2][c2] = 1
        bad += accepts(g)
    check(f"no single-star relocation accepted ({len(moves)} variants"
          f"{'' if full else ', sampled'})", bad == 0, f"{bad} false accepts")

    # rectangle swaps preserve row and column counts exactly, so they isolate
    # the region and adjacency rules from the counting rules.
    iso_adj = iso_reg = None
    swaps = 0
    bad = 0
    for i, (r1, c1) in enumerate(stars):
        for (r2, c2) in stars[i + 1:]:
            if r1 == r2 or c1 == c2 or grid[r1][c2] or grid[r2][c1]:
                continue
            g = [row[:] for row in grid]
            g[r1][c1] = g[r2][c2] = 0
            g[r1][c2] = g[r2][c1] = 1
            swaps += 1
            R, A = regs_ok(g), adj_ok(g)
            if R and not A and iso_adj is None:
                iso_adj = g
            if A and not R and iso_reg is None:
                iso_reg = g
            bad += accepts(g)
    check(f"no rectangle swap accepted ({swaps}, row+column counts preserved)", bad == 0)
    check("rejects a placement breaking ONLY adjacency", iso_adj and not accepts(iso_adj))
    check("rejects a placement breaking ONLY regions", iso_reg and not accepts(iso_reg))
    random.seed(7)
    rnd = 0
    for _ in range(200):
        g = [[0] * W for _ in range(W)]
        for _ in range(22):
            g[random.randrange(W)][random.randrange(W)] = 1
        rnd += accepts(g)
    check("200 random 22-star placements rejected", rnd == 0)
    o0, s0 = play([0] * 121)
    check("all-zero rejects and prints EMPTY SKY",
          not any(s0) and "".join(chr(o) for o in o0 if o) == "EMPTY SKY")

    print("\n== E. Protocol edges ==")
    check("nothing emitted after the message",
          "".join(chr(o) for o in play(bits, tail=200)[0] if o) == "(* TWO STARS *)")
    check("bits past the 121st are ignored", any(play(bits + [1] * 20, tail=20)[1]))
    check("enable=0 blocks acceptance", not any(play(bits, enable=0)[1]))
    check("a leading blank row misaligns the grid and rejects",
          not any(play([0] * 11 + bits, tail=20)[1]))
    sim.reset_state()
    for _ in range(4):
        sim.cycle(sim.make_inputs(rst_n=0, enable=0, I=0))
    for b in bits[:50]:
        sim.cycle(sim.make_inputs(rst_n=1, enable=1, I=b))
    for _ in range(4):
        sim.cycle(sim.make_inputs(rst_n=0, enable=0, I=0))
    ok = False
    for b in bits + [0] * 4:
        sim.cycle(sim.make_inputs(rst_n=1, enable=1, I=b))
        ok |= sim.port("success")
    check("rst_n re-arms after an aborted attempt", ok)

    print("\n== F. Netlist sanity ==")
    drv = collections.Counter()
    for li in range(len(nl.insts)):
        for pin, net in nl.conns[li].items():
            if pin in OUTPUT_PINS:
                drv[net] += 1
    ports = {nl.ports[p] for p in IN}
    undriven = [nl.net_name[n] for n in nl.net_pins
                if n not in drv and n not in nl.power and n not in ports]
    check("no multiply-driven nets", not [n for n, c in drv.items() if c > 1])
    check("exactly one undriven net, n575", undriven == ["n575"], str(undriven))

    print("\n== G. The generator emits five distinct messages ==")

    def message(g):
        out, _ = play([g[r][c] for r in range(W) for c in range(W)], tail=25)
        return "".join(chr(o) for o in out if o)

    def profile(g):
        st = [(r, c) for r, c in cells if g[r][c]]
        rc = collections.Counter(REGIONS[r][c] for r, c in st)
        return (len(st) == 0,
                all(sum(g[r]) == 2 for r in range(W)),
                all(sum(g[r][c] for r in range(W)) == 2 for c in range(W)),
                all(rc[l] == 2 for l in LETTERS),
                adj_ok(g))

    empty_grid = [[0] * W for _ in range(W)]
    one_star = [[1 if (r, c) == (0, 0) else 0 for c in range(W)] for r in range(W)]
    check("legal placement -> '(* TWO STARS *)'", message(grid) == "(* TWO STARS *)")
    check("empty board -> 'EMPTY SKY'", message(empty_grid) == "EMPTY SKY")
    check("a single star -> 'TRY AGAIN'", message(one_star) == "TRY AGAIN")
    # Every count correct, adjacency alone broken: its own message. Found only by
    # constructing the case deliberately -- random stimulus never produces one.
    check("counts correct, only adjacency broken -> 'TWO\"NOT TOUCH'",
          iso_adj is not None and message(iso_adj) == 'TWO"NOT TOUCH',
          repr(message(iso_adj)) if iso_adj else "no such placement found")
    # The opposite extreme from EMPTY SKY. Fires at exactly 121 stars; 120 does not.
    full_grid = [[1] * W for _ in range(W)]
    almost = [[1] * W for _ in range(W)]
    almost[W - 1][W - 1] = 0
    check("every cell a star -> 'BIG BANG'", message(full_grid) == "BIG BANG",
          repr(message(full_grid)))
    check("one cell short of full -> 'TRY AGAIN'", message(almost) == "TRY AGAIN",
          repr(message(almost)))

    print("\n== H. Easter eggs ==")
    from tools import eggs
    m = eggs.bars()
    check("36 layer-200/0 stamps decode as Morse",
          eggs.decode(eggs.morse(m)) == "PER ARENAM AD ASTRA",
          repr(eggs.decode(eggs.morse(m))))

    print("\nRESULT:", "ALL CHECKS PASS" if not _fails else f"{len(_fails)} FAILURES: {_fails}")
    return 1 if _fails else 0


if __name__ == "__main__":
    sys.exit(main(full="--full" in sys.argv))
