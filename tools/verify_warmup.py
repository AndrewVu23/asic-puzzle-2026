"""Validate the GDS extractor against the warm-up's known-good DEF + netlist."""
from __future__ import annotations

if __package__ in (None, ""):        # allow `python3 tools/x.py` as well as `-m tools.x`
    import os as _os, sys as _sys
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))


def _p(*parts):
    """Path relative to the repo root, so the tools work from any cwd."""
    import os.path
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(here), *parts)

import collections, sys
from tools.extract import Extractor
from tools.defparse import parse, def_to_gds_origin


def outline(lib, cn):
    s = lib.structs[cn]
    for pref in ((81, 4), (236, 0)):
        for b in s.boundaries:
            if (b.layer, b.datatype) == pref:
                xs = [p[0] for p in b.xy]; ys = [p[1] for p in b.xy]
                return max(xs) - min(xs), max(ys) - min(ys)
    raise KeyError(cn)


def main(gds=None, def_=None):
    e = Extractor(gds or _p("warmup", "04_final.gds")).run()
    comps, nets = parse(def_ or _p("warmup", "03_post_place_and_route.def"))
    for l in e.log:
        print("   ", l)

    want = {}
    for nm, (cell, x, y, o) in comps.items():
        w, h = outline(e.lib, cell)
        want[def_to_gds_origin(x, y, o, w, h) + (cell,)] = nm
    got = {(x, y, r, a, c): i for i, (_, c, x, y, r, a) in enumerate(e.insts)}
    ok_place = len(set(want) & set(got))
    print(f"\n[1] PLACEMENT   {ok_place}/{len(want)} DEF components matched "
          f"({len(got)} extracted)")
    for k in list(set(want) - set(got))[:5]:
        print("      DEF-only:", want[k], k)

    idx2def = {got[k]: want[k] for k in set(want) & set(got)}
    mine = collections.defaultdict(set)
    for net, pins in e.pins_by_net.items():
        for ii, pin in pins:
            if ii in idx2def:
                mine[net].add((idx2def[ii], pin))
    for port, net in e.port_labels().items():
        mine[net].add(("__PORT__", port))

    allpins = {p for v in nets.values() for p in v}
    pin2my = {}
    for net, pins in mine.items():
        for p in pins:
            pin2my[p] = net
    found = sum(1 for p in allpins if p in pin2my)
    print(f"[2] PIN COVERAGE {found}/{len(allpins)} DEF pin-instances located")

    def_sets = {frozenset(v) for v in nets.values() if v}
    mine_sets = {frozenset(v) for v in mine.values() if v}
    print(f"[3] NET IDENTITY {len(def_sets & mine_sets)}/{len(nets)} DEF nets "
          f"reproduced exactly ({len(mine_sets)} extracted)")

    frag, merged = [], []
    for nname, pins in nets.items():
        g = collections.Counter(pin2my.get(p, "MISSING") for p in pins)
        if len(g) > 1:
            frag.append((nname, len(pins), len(g), g.get("MISSING", 0)))
    for net, pins in mine.items():
        owners = {n for n, dp in nets.items() for p in pins if p in dp}
        if len(owners) > 1:
            merged.append((sorted(owners), len(pins)))
    print(f"[4] FRAGMENTED   {len(frag)} DEF nets split across >1 extracted net")
    for n, np_, ng, mi in sorted(frag, key=lambda t: -t[2])[:10]:
        print(f"      {n:26s} pins={np_:3d} pieces={ng:3d} missing={mi}")
    print(f"[5] SHORTED      {len(merged)} extracted nets spanning >1 DEF net")
    for o, npin in merged[:10]:
        print(f"      {o} ({npin} pins)")

    clean = (ok_place == len(want) and found == len(allpins)
             and not frag and not merged)
    print("\nRESULT:", "PASS - extraction matches DEF exactly" if clean else "FAIL")
    return 0 if clean else 1


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
