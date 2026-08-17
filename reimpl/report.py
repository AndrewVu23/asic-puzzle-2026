"""Compare the re-implemented chip against the original recovered from puzzle.gds.

Reads the newest LibreLane run's final metrics and puts them next to the original's
measured cell inventory and area.
"""
import glob, json, os, re, sys, collections

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)


def liberty_areas():
    pdk = sorted(glob.glob(os.path.expanduser(
        "~/.ciel/ciel/sky130/versions/*/")))[0]
    lib = (pdk + "sky130A/libs.ref/sky130_fd_sc_hd/lib/"
                 "sky130_fd_sc_hd__tt_025C_1v80.lib")
    area, cur = {}, None
    for line in open(lib):
        m = re.match(r'\s*cell\s*\(\s*"?([A-Za-z0-9_]+)"?\s*\)', line)
        if m:
            cur = m.group(1)
            continue
        if cur:
            a = re.match(r'\s*area\s*:\s*([0-9.]+)\s*;', line)
            if a:
                area[cur] = float(a.group(1))
                cur = None
    return area


def original():
    from tools.netlist import Netlist, base_cell
    area = liberty_areas()
    nl = Netlist(os.path.join(ROOT, "puzzle.gds"),
                 ["clk", "rst_n", "enable", "I"],
                 [f"O[{i}]" for i in range(8)] + ["success"])
    logic = len(nl.insts)
    hist = collections.Counter(base_cell(c) for _n, c, *_ in nl.insts)
    return {
        "cells": logic,
        "flops": sum(v for k, v in hist.items() if k.startswith("df")),
        "cell_area": sum(area.get(c, 0.0) for _n, c, *_ in nl.insts),
        "fillers": len(nl.e.insts) - logic,
        "die_area": 200.0 * 300.0,
    }


def reimplementation():
    runs = sorted(glob.glob(os.path.join(HERE, "flow", "runs", "RUN_*")))
    if not runs:
        return None, None
    run = runs[-1]
    mf = os.path.join(run, "final", "metrics.json")
    if not os.path.exists(mf):
        return run, None
    return run, json.load(open(mf))


def main():
    o = original()
    run, m = reimplementation()
    print("\nORIGINAL  (recovered from puzzle.gds)")
    print(f"  logic cells              {o['cells']}")
    print(f"  flip-flops               {o['flops']}")
    print(f"  standard-cell area       {o['cell_area']:.0f} um^2")
    print(f"  tap/decap fillers        {o['fillers']}")
    print(f"  die                      200 x 300 um = {o['die_area']:.0f} um^2")
    print(f"  utilisation              {100*o['cell_area']/o['die_area']:.1f}%")

    if m is None:
        print(f"\nNo finished LibreLane run found under {HERE}/flow/runs")
        return
    print(f"\nRE-IMPLEMENTATION  ({os.path.basename(run)})")
    g = m.get
    print(f"  standard cells           {g('design__instance__count__stdcell')}"
          f"  (of which {g('design__instance__count__class:timing_repair_buffer', 0)}"
          f" timing-repair buffers, {g('design__instance__count__class:clock_buffer', 0)} clock buffers)")
    print(f"  flip-flops               {g('design__instance__count__class:sequential_cell')}")
    print(f"  tap/decap fillers        {g('design__instance__count__class:fill_cell', 0)}"
          f" + {g('design__instance__count__class:tap_cell', 0)} taps")
    print(f"  standard-cell area       {g('design__instance__area__stdcell', 0):.0f} um^2"
          f"  (incl. fill: {g('design__instance__area', 0):.0f})")
    print(f"  die area                 {g('design__die__area', 0):.0f} um^2")
    print(f"  routed wirelength        {g('route__wirelength')} um")
    print("  setup worst slack, by corner:")
    for k, v in sorted(m.items()):
        if k.startswith("timing__setup__ws__corner:"):
            corner = k.split(":", 1)[1]
            print(f"      {corner:22s} {v:+.3f} ns "
                  f"{'' if v >= 0 else '  <-- VIOLATION'}")
    print(f"  hold worst slack         {g('timing__hold__ws', 0):+.3f} ns")
    for label, key in (("magic DRC errors", "magic__drc_error__count"),
                       ("klayout DRC errors", "klayout__drc_error__count"),
                       ("router DRC errors", "route__drc_errors"),
                       ("LVS errors", "design__lvs_error__count"),
                       ("antenna violations", "antenna__violating__nets"),
                       ("max slew violations", "design__max_slew_violation__count")):
        if key in m:
            print(f"  {label:24s} {m[key]}")

    for label, pat in (("GDS", "final/gds/*.gds"),
                       ("post-PnR netlist", "final/nl/*.v"),
                       ("layout render", "final/render/*.png")):
        f = glob.glob(os.path.join(run, pat))
        if f:
            print(f"  {label:24s} {os.path.relpath(f[0], HERE)}"
                  f"  ({os.path.getsize(f[0])/1024:.0f} KB)")
    print()


if __name__ == "__main__":
    main()
