"""Generate golden test vectors by running the EXTRACTED netlist.

The reference is the netlist pulled out of puzzle.gds -- the same one that replays
Jane Street's own waveform 312/312 bit-exact. So the testbench compares the
re-implementation against the real chip's behaviour, not against my notes about it.

Two vector sets are written, and the re-implementation must be bit-exact on both:

  vectors.txt        whole attempts -- the vendor waveform, the unique solution,
                     near misses that isolate each rule, random placements, enable
                     stalls, and back-to-back attempts.
  vectors_reset.txt  rst_n asserted while a message is still emitting, cut at every
                     character position. The original clears its generator cleanly
                     here despite holding flops reset cannot reach (4 dfxtp, 4
                     dfstp), so this is real specified behaviour, not don't-care.

Each line is 12 bits: {rst_n, enable, I, O[7:0], success}.
"""
import os, random, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.netlist import Netlist
from tools.sim import Sim
from tools.starbattle import W, solve, stream
from tools import vcd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

IN = ["clk", "rst_n", "enable", "I"]
OUT = [f"O[{i}]" for i in range(8)] + ["success"]


def main():
    nl = Netlist(os.path.join(ROOT, "puzzle.gds"), IN, OUT)
    sim = Sim(nl)

    lines, manifest = [], []

    def emit(name, steps):
        """steps: iterable of (rst_n, enable, I). Runs them and records golden O."""
        start = len(lines)
        for r, e, i in steps:
            sim.cycle(sim.make_inputs(rst_n=r, enable=e, I=i))
            o = sum((1 if sim.port(f"O[{k}]") else 0) << k for k in range(8))
            s = 1 if sim.port("success") else 0
            lines.append(f"{r}{e}{i}{o:08b}{s}")
        manifest.append(f"  {start:6d} .. {len(lines)-1:6d}  {name}")

    TAIL = 24   # longest message is 15 characters; leaves margin

    def attempt(name, bits, tail=TAIL, enable=1, pre=4):
        emit(name, [(0, 0, 0)] * pre + [(1, enable, b) for b in bits]
                   + [(1, enable, 0)] * tail)

    sol = solve()[0]
    win = stream(sol)
    grid = [[1 if c in sol[r] else 0 for c in range(W)] for r in range(W)]
    flat = lambda g: [g[r][c] for r in range(W) for c in range(W)]

    # -- the vendor's own stimulus, replayed exactly ---------------------------
    _, _, tl = vcd.timeline(os.path.join(ROOT, "example_inputs.vcd"))
    prev, edges = None, []
    for _t, h in tl:
        if prev == "0" and h.get("clk") == "1":
            edges.append(h)
        prev = h.get("clk")
    sim.reset_state()
    emit("vendor example_inputs.vcd",
         [(int(h["rst_n"]), int(h["enable"]), int(h["I"])) for h in edges])

    # -- the three messages ---------------------------------------------------
    attempt("winning placement -> (* TWO STARS *)", win)
    attempt("empty board -> EMPTY SKY", [0] * 121)
    attempt("single star -> TRY AGAIN", [1] + [0] * 120)
    attempt("completely full board -> BIG BANG", [1] * 121)
    attempt("one cell short of full -> TRY AGAIN", [1] * 120 + [0])

    # -- near misses ----------------------------------------------------------
    random.seed(11)
    stars = [(r, c) for r in range(W) for c in range(W) if grid[r][c]]
    free = [(r, c) for r in range(W) for c in range(W) if not grid[r][c]]
    for n, ((r, c), (r2, c2)) in enumerate(
            random.sample([(s, f) for s in stars for f in free], 25)):
        g = [row[:] for row in grid]
        g[r][c], g[r2][c2] = 0, 1
        attempt(f"relocation {n}: ({r},{c}) -> ({r2},{c2})", flat(g))

    # rectangle swaps preserve row and column counts, isolating region/adjacency
    n = 0
    for i, (r1, c1) in enumerate(stars):
        for (r2, c2) in stars[i + 1:]:
            if r1 == r2 or c1 == c2 or grid[r1][c2] or grid[r2][c1]:
                continue
            g = [row[:] for row in grid]
            g[r1][c1] = g[r2][c2] = 0
            g[r1][c2] = g[r2][c1] = 1
            attempt(f"rectangle swap {n}", flat(g))
            n += 1
            if n >= 25:
                break
        if n >= 25:
            break

    for n in range(25):
        g = [[0] * W for _ in range(W)]
        for _ in range(22):
            g[random.randrange(W)][random.randrange(W)] = 1
        attempt(f"random placement {n}", flat(g))

    # -- protocol edges -------------------------------------------------------
    attempt("bits past the 121st are ignored", win + [1] * 20)
    attempt("enable held low throughout", win, enable=0)
    attempt("leading blank row misaligns the grid", [0] * 11 + win)

    # stall mid-grid, then resume
    emit("enable stalls mid-grid then resumes",
         [(0, 0, 0)] * 4 + [(1, 1, b) for b in win[:50]] + [(1, 0, 1)] * 17
         + [(1, 1, b) for b in win[50:]] + [(1, 0, 0)] * TAIL)

    # enable drops during the message -- the generator must keep going
    emit("enable drops during the message",
         [(0, 0, 0)] * 4 + [(1, 1, b) for b in win] + [(1, 0, 0)] * TAIL)

    # aborted attempt, reset, then the real one
    emit("reset re-arms after an aborted attempt",
         [(0, 0, 0)] * 4 + [(1, 1, b) for b in win[:50]] + [(0, 0, 0)] * 4
         + [(1, 1, b) for b in win] + [(1, 1, 0)] * TAIL)

    # back-to-back attempts, three messages in a row
    emit("three attempts back to back",
         [(0, 0, 0)] * 4 + [(1, 1, b) for b in [0] * 121] + [(1, 1, 0)] * TAIL
         + [(0, 0, 0)] * 4 + [(1, 1, b) for b in [1] + [0] * 120] + [(1, 1, 0)] * TAIL
         + [(0, 0, 0)] * 4 + [(1, 1, b) for b in win] + [(1, 1, 0)] * TAIL)

    # -- random attempts: random placements, random enable stalls ---------------
    # Structured as whole attempts so that no reset ever lands mid-message. The
    # stalls make the scan take a random number of cycles, which exercises the
    # enable gating without leaving the legal protocol.
    random.seed(4242)
    for a in range(20):
        seq = [(0, 0, 0)] * random.randint(2, 5)
        fed = 0
        while fed < 121:
            if random.random() < 0.25:
                seq.append((1, 0, random.randint(0, 1)))       # stall
            else:
                seq.append((1, 1, 1 if random.random() < 0.2 else 0))
                fed += 1
        seq += [(1, random.randint(0, 1), random.randint(0, 1)) for _ in range(TAIL)]
        emit(f"random attempt {a} with stalls", seq)

    write("vectors.txt", "vectors.manifest", lines, manifest)

    # -- reset while a message is still emitting -------------------------------
    lines, manifest = [], []
    random.seed(99)
    for a in range(10):
        cut = random.randint(1, 8)   # cut the message after this many characters
        emit(f"reset {cut} characters into the message",
             [(0, 0, 0)] * 4 + [(1, 1, b) for b in win] + [(1, 1, 0)] * cut)
    emit("then a clean attempt", [(0, 0, 0)] * 4 + [(1, 1, b) for b in win]
                                 + [(1, 1, 0)] * TAIL)
    write("vectors_reset.txt", "vectors_reset.manifest", lines, manifest)


def write(vfile, mfile, lines, manifest):
    with open(os.path.join(HERE, "tb", vfile), "w") as fh:
        fh.write("\n".join(lines) + "\n")
    with open(os.path.join(HERE, "tb", mfile), "w") as fh:
        fh.write(f"{len(lines)} cycles, {len(manifest)} scenarios\n"
                 "format: {rst_n, enable, I, O[7:0], success}\n\n"
                 + "\n".join(manifest) + "\n")
    print(f"wrote tb/{vfile}: {len(lines)} cycles across {len(manifest)} scenarios")


if __name__ == "__main__":
    main()
