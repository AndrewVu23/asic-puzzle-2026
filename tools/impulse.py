"""Impulse response of the checker: which accumulators does each grid cell feed?

Reset, run 140 cycles of I=0, record the final flop state. That is the baseline.
Then, for each cell k, repeat with I=1 at cycle k alone and diff the final state.

The set of cells that permanently move a given flop *is* that flop's address map,
measured rather than inferred. Column counters come out periodic with period 11;
region counters come out as the region shapes; the total counter moves for every
cell. Writes out/impulse.png.
"""
import os, sys, collections
if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.netlist import Netlist
from tools.sim import Sim
from tools.analyze import Analysis
from tools.starbattle import REGIONS

W, NCELL, NCYC = 11, 121, 140
IN = ["clk", "rst_n", "enable", "I"]
OUT = [f"O[{i}]" for i in range(8)] + ["success"]


def run(sim, nl, star_at=None):
    sim.reset_state()
    seq = [(0, 0, 0)] * 4 + [(1, 1, 1 if k == star_at else 0) for k in range(NCYC)]
    for r, e, i in seq:
        sim.cycle(sim.make_inputs(rst_n=r, enable=e, I=i))
    return tuple(bool(sim.v.get(nl.conns[li]["Q"])) for li in sim.flops)


def main():
    nl = Netlist(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "puzzle.gds"), IN, OUT)
    sim = Sim(nl)

    # Scope to the `success` cone. The message-generator flops alsodiffer between
    # runs, simply because a different message is being emitted, and that says
    # nothing about which accumulator a cell feeds.
    an = Analysis(nl)
    _, seeds = an.cone(nl.ports["success"])          # flops feeding success directly
    cone_flops, todo = set(seeds), list(seeds)       # then transitively behind those
    while todo:
        u = todo.pop()
        for pin, net in nl.conns[u].items():
            if pin in ("Q", "Q_N"):
                continue
            _, fs = an.cone(net)
            for f in fs:
                if f not in cone_flops:
                    cone_flops.add(f); todo.append(f)
    keep = [i for i, li in enumerate(sim.flops) if li in cone_flops]
    print(f"success-cone flops: {len(keep)} of {len(sim.flops)}")

    base = run(sim, nl)
    hits = collections.defaultdict(set)          # flop -> set of cells that move it
    for k in range(NCELL):
        st = run(sim, nl, k)
        for f in keep:
            if base[f] != st[f]:
                hits[f].add(k)

    cols = {c: {k for k in range(NCELL) if k % W == c} for c in range(W)}
    rgns = {}
    for r, row in enumerate(REGIONS):
        for c, ch in enumerate(row):
            rgns.setdefault(ch, set()).add(r * W + c)

    label = {}
    for f, s in hits.items():
        if len(s) == NCELL:
            label[f] = ("total", "total star count")
        elif any(s == v for v in cols.values()):
            c = next(k for k, v in cols.items() if v == s)
            label[f] = ("col", f"column {c}")
        elif any(s == v for v in rgns.values()):
            g = next(k for k, v in rgns.items() if v == s)
            label[f] = ("rgn", f"region {g}")
        elif len(s) == 1:
            # a delay-line stage: the only cell that still moves it is the one it is
            # still holding when the scan freezes, so the delay follows directly
            label[f] = ("other", f"delay {NCELL - min(s)}")
        else:
            label[f] = ("other", f"flop {f}")

    kinds = collections.Counter(v[0] for v in label.values())
    print(f"flops permanently moved by at least one cell: {len(hits)}")
    for k, n in sorted(kinds.items()):
        print(f"  {k:6s} {n}")
    print(f"\nchanged-set size per cell: "
          f"{sorted(set(sum(1 for s in hits.values() if k in s) for k in range(NCELL)))}")
    return hits, label




def figure(hits, label, path="impulse.svg"):
    """The whole architecture in one picture, entirely from measurement.

    Emitted as raw SVG: matplotlib cannot load here (the same broken `pyexpat`
    that made `pip` unreliable), and vector output is what a writeup wants anyway.
    """
    CW, CH, LEFT, TOP = 11, 13, 132, 74      # cell w/h, label gutter, header
    RIGHT, BOT = 250, 74
    order, groups = [], []
    note = {"col": "D sees col[3:0] only  \u2192  fan-in 7",
            "rgn": "D sees col[3:0] AND row[3:0]  \u2192  fan-in 11",
            "total": "D sees neither index",
            "other": "D sees only the previous stage  \u2192  fan-in 3"}
    for kind, pretty in (("col", "column counters"), ("rgn", "region counters"),
                         ("total", "total"), ("other", "adjacency delay line")):
        def key(f):
            t = label[f][1].split()[-1]
            return (int(t), "") if t.isdigit() else (0, t)
        grp = sorted(((key(f), f) for f in hits if label[f][0] == kind))
        if grp:
            groups.append((len(order), len(grp), pretty, kind))
            order += [f for _, f in grp]
    W_px = LEFT + NCELL * CW + RIGHT
    H_px = TOP + len(order) * CH + BOT
    col = {"col": "#2563eb", "rgn": "#dc2626", "total": "#15803d", "other": "#9333ea"}
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W_px}" height="{H_px}" '
         f'viewBox="0 0 {W_px} {H_px}" font-family="ui-sans-serif,Helvetica,Arial">',
         f'<rect width="{W_px}" height="{H_px}" fill="#ffffff"/>',
         f'<text x="8" y="24" font-size="15" font-weight="600" fill="#0f172a">'
         f'Impulse response: which accumulator does each grid cell permanently move?</text>',
         f'<text x="8" y="44" font-size="11.5" fill="#475569">'
         f'Reset, 140 cycles of I=0 as the baseline. Then one star at cell k, and diff the '
         f'final state of the 79 flops in the success cone.</text>',
         f'<text x="8" y="60" font-size="11.5" fill="#475569">'
         f'Nothing here is inferred: each row is the measured set of cells that move that '
         f'flop, which is the flop&#8217;s address map.</text>']
    for x in range(0, NCELL + 1, W):                      # one gridline per grid row
        gx = LEFT + x * CW
        o.append(f'<line x1="{gx}" y1="{TOP}" x2="{gx}" y2="{TOP+len(order)*CH}" '
                 f'stroke="#cbd5e1" stroke-width="1"/>')
    for y, f in enumerate(order):
        gy = TOP + y * CH
        o.append(f'<text x="{LEFT-7}" y="{gy+CH-3.5}" font-size="9.5" text-anchor="end" '
                 f'fill="#334155">{label[f][1]}</text>')
        for k in sorted(hits[f]):
            o.append(f'<rect x="{LEFT+k*CW+0.6}" y="{gy+0.6}" width="{CW-1.2}" '
                     f'height="{CH-1.2}" fill="{col[label[f][0]]}" rx="1.5"/>')
    for start, n, pretty, kind in groups:
        gy = TOP + start * CH
        if start:
            o.append(f'<line x1="8" y1="{gy}" x2="{LEFT+NCELL*CW}" y2="{gy}" '
                     f'stroke="#334155" stroke-width="1.2"/>')
        o.append(f'<text x="{LEFT+NCELL*CW+10}" y="{gy+n*CH/2-2}" font-size="10.5" '
                 f'font-weight="600" fill="{col[kind]}">{pretty}</text>')
        o.append(f'<text x="{LEFT+NCELL*CW+10}" y="{gy+n*CH/2+11}" font-size="8.5" '
                 f'fill="#64748b">{note[kind]}</text>')
    ybase = TOP + len(order) * CH
    for k in range(0, NCELL, W):
        o.append(f'<text x="{LEFT+k*CW+2}" y="{ybase+14}" font-size="9" fill="#475569">'
                 f'{k}</text>')
        o.append(f'<text x="{LEFT+k*CW+2}" y="{ybase+25}" font-size="8.5" fill="#94a3b8">'
                 f'row {k//W}</text>')
    o.append(f'<text x="{LEFT}" y="{ybase+41}" font-size="11" fill="#0f172a">'
             f'cell index of the single injected star, raster order, 11 per row</text>')
    o.append(f'<text x="8" y="{H_px-8}" font-size="9.5" fill="#64748b">'
             f'The bimodal fan-in is visible as shape. Column rows are strictly periodic '
             f'with period 11, so those counters are addressed by the column index alone. '
             f'Region rows are 2-D blobs, so those need the row index too.</text>')
    o.append(f'<text x="8" y="{H_px-22}" font-size="9.5" fill="#64748b">'
             f'Those four extra row bits are the entire difference between a D fan-in of 7 '
             f'and one of 11, the single most confusing measurement in the project.</text>')
    o.append('</svg>')
    io.open(path, "w").write("\n".join(o))
    print("wrote", path)


def figure_grid(hits, label, path="impulse.svg"):
    """Same measurement, drawn as boards instead of as a strip.

    One 11x11 board per flip-flop, with the cells that permanently move it filled
    in. Column counters come out as vertical stripes, region counters as the region
    shapes themselves, and nothing has to be inferred to see it.
    """
    S, GAP, LAB = 7, 22, 15                       # cell px, gap between boards, label px
    BW = W * S                                    # board width
    PAD, TOP = 16, 118
    per = {"col": 11, "rgn": 11, "tail": 13}
    groups = []
    for kind, title in (("col", "11 COLUMN COUNTERS"),
                        ("rgn", "11 REGION COUNTERS"),
                        ("tail", "TOTAL, then the 12 ADJACENCY DELAY STAGES")):
        want = ("total", "other") if kind == "tail" else (kind,)
        def key(f):
            t = label[f][1].split()[-1]
            return (0, int(t)) if t.isdigit() else (1, t)
        grp = sorted((f for f in hits if label[f][0] in want), key=key)
        if kind == "tail":
            grp = ([f for f in grp if label[f][0] == "total"] +
                   [f for f in grp if label[f][0] == "other"])
        groups.append((title, kind, grp))

    ncol = max(per.values())
    Wpx = PAD * 2 + ncol * BW + (ncol - 1) * GAP
    Hpx = TOP + len(groups) * (BW + LAB + 46) + 40
    col = {"col": "#2563eb", "rgn": "#dc2626", "total": "#15803d", "other": "#9333ea"}
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{Wpx}" height="{Hpx}" '
         f'viewBox="0 0 {Wpx} {Hpx}" font-family="ui-sans-serif,Helvetica,Arial">',
         f'<rect width="{Wpx}" height="{Hpx}" fill="#ffffff"/>',
         f'<text x="{PAD}" y="30" font-size="17" font-weight="600" fill="#0f172a">'
         f'What each accumulator in the chip is watching</text>',
         f'<text x="{PAD}" y="54" font-size="12.5" fill="#334155">'
         f'Every square below is the 11 x 11 board. A cell is filled when putting a single '
         f'star there, and nothing else, permanently changes that one flip-flop.</text>',
         f'<text x="{PAD}" y="73" font-size="12.5" fill="#334155">'
         f'So each picture is what that flip-flop counts. Measured by running the chip 121 '
         f'times, once per cell. Nothing is inferred.</text>',
         f'<text x="{PAD}" y="97" font-size="12.5" fill="#475569">'
         f'The columns come out as stripes and the regions come out as the region map, '
         f'which is the whole architecture in one image.</text>']
    y = TOP
    for title, kind, grp in groups:
        o.append(f'<text x="{PAD}" y="{y-8}" font-size="12" font-weight="600" '
                 f'fill="#0f172a">{title}</text>')
        for n, f in enumerate(grp):
            x0 = PAD + n * (BW + GAP)
            c = col[label[f][0]]
            for k in range(NCELL):
                r, cc = divmod(k, W)
                on = k in hits[f]
                o.append(f'<rect x="{x0+cc*S}" y="{y+r*S}" width="{S-0.8}" '
                         f'height="{S-0.8}" fill="{c if on else "#eef2f7"}"/>')
            o.append(f'<text x="{x0+BW/2}" y="{y+BW+13}" font-size="10" '
                     f'text-anchor="middle" fill="#334155">{label[f][1]}</text>')
        y += BW + LAB + 46
    o.append('</svg>')
    io.open(path, "w").write("\n".join(o))
    print("wrote", path)


def verify(hits, label, svg_path):
    """Cross-check the measured address maps against ground truth, and the drawn
    SVG against the measurement. Ground truth here is the region map read off the
    silicon in Part V, plus plain arithmetic for the columns."""
    import re
    cols = {c: {k for k in range(NCELL) if k % W == c} for c in range(W)}
    rgns = {}
    for r, row in enumerate(REGIONS):
        for c, ch in enumerate(row):
            rgns.setdefault(ch, set()).add(r * W + c)
    by = lambda kind: {label[f][1]: hits[f] for f in hits if label[f][0] == kind}
    ok = []

    got = by("col")
    assert len(got) == W, f"expected {W} column counters, got {len(got)}"
    for c in range(W):
        assert got[f"column {c}"] == cols[c], f"column {c} address map wrong"
    ok.append(f"11 column counters match k mod 11 exactly")

    got = by("rgn")
    assert len(got) == len(rgns), f"expected {len(rgns)} region counters, got {len(got)}"
    for g, cells in rgns.items():
        assert got[f"region {g}"] == cells, f"region {g} address map wrong"
    union = set().union(*rgns.values())
    assert union == set(range(NCELL)) and \
        sum(len(v) for v in rgns.values()) == NCELL, "regions do not partition the grid"
    ok.append(f"{len(rgns)} region counters reproduce the region map, and it partitions the grid")

    got = by("total")
    assert len(got) == 1 and next(iter(got.values())) == set(range(NCELL))
    ok.append("total counter moves for every one of the 121 cells")

    got = by("other")
    assert got == {f"delay {NCELL-k}": {k} for k in range(NCELL - 12, NCELL)}, \
        "delay line does not match the last 12 cells"
    ok.append("12 delay stages match cells 109..120, one each")

    # and the drawing agrees with the measurement
    svg = io.open(svg_path).read()
    drawn = len(re.findall(r'<rect x="\d', svg))
    assert drawn == sum(len(v) for v in hits.values()), \
        f"SVG has {drawn} marks, measurement has {sum(len(v) for v in hits.values())}"
    ok.append(f"SVG contains exactly {drawn} marks, one per measured (cell, flop) pair")

    print("\nself-check:")
    for line in ok:
        print("  PASS  " + line)


if __name__ == "__main__":
    import io
    h, l = main()
    out = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "impulse.svg")
    figure(h, l, out)
    verify(h, l, out)
    figure_grid(h, l, out.replace("impulse.svg", "impulse-boards.svg"))
