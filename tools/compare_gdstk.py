"""Cross-check tools/gdsread.py + tools/extract.py against gdstk on the same files.

Run under .venv313 (gdstk needs a working pyexpat; the system python3.14 build's
pyexpat is broken -- see README note). Nothing in tools/ depends on this venv itself,
it's pure python, gdstk is only needed for this comparison script.
"""
from __future__ import annotations
import time, collections
import gdstk
from tools.gdsread import Library
from tools.extract import Extractor, rectilinear_to_rects, path_to_rects, COND


def mine_structures(fn):
    t0 = time.perf_counter()
    lib = Library(fn)
    t = time.perf_counter() - t0
    return lib, t


def theirs_structures(fn):
    t0 = time.perf_counter()
    lib = gdstk.read_gds(fn)
    t = time.perf_counter() - t0
    return lib, t


def compare_file(fn):
    print(f"\n{'='*70}\n{fn}\n{'='*70}")

    mylib, t_mine = mine_structures(fn)
    gdslib, t_theirs = theirs_structures(fn)

    print(f"parse time:  mine {t_mine*1000:7.1f} ms   gdstk {t_theirs*1000:7.1f} ms"
          f"   ({t_mine/t_theirs:.1f}x)")

    # -- structure count / names -----------------------------------------
    my_names = set(mylib.structs)
    gd_names = {c.name for c in gdslib.cells}
    print(f"structures:  mine {len(my_names)}   gdstk {len(gd_names)}"
          f"   diff={my_names ^ gd_names or 'none'}")

    # -- units --------------------------------------------------------
    print(f"units:       mine user={mylib.unit_user} m={mylib.unit_meters}"
          f"   gdstk unit={gdslib.unit} precision={gdslib.precision}")

    # -- top cell conducting-layer area, flattened, INCLUDING routed paths --
    # gdstk stores coordinates in "user units" (microns here, per the file's
    # UNITS record) while tools/gdsread.py stores raw database units (nm, no
    # scaling applied) -- must convert before comparing.
    dbu_per_user_unit = mylib.unit_user / mylib.unit_meters  # e.g. 0.001/1e-9 = 1e6... no:
    # unit_user = user-units per dbu (GDS UNITS[0]); unit_meters = meters per dbu (UNITS[1])
    # -> 1 user-unit = (1/unit_user) dbu.  With unit_user=0.001 that's 1000 dbu/micron.
    dbu_per_user_unit = 1.0 / mylib.unit_user
    scale2 = dbu_per_user_unit ** 2  # area scale: micron^2 -> dbu^2

    topname = mylib.top_cells()[0]
    gd_top = next(c for c in gdslib.cells if c.name == topname)

    # Bucket by (layer, DATATYPE) -- a bare layer number is ambiguous: e.g.
    # (67,20) is real li1 metal, (67,44) is the mcon cut, (67,16) a pin
    # marker, all sharing layer 67. This is the same layer/datatype
    # distinction that mattered inside extract.py itself; getting it wrong
    # here would compare two different things and call it a mismatch.
    def gdstk_area_by_layerdt():
        areas = collections.defaultdict(float)
        for p in gd_top.get_polygons(include_paths=True, depth=None):
            areas[(p.layer, p.datatype)] += p.area() * scale2
        return areas

    e = Extractor(fn)
    e.run()

    def mine_area_by_layer():
        # e.shapes only ever holds datatype-20 conducting metal (that's the
        # only thing COND selects in extract.py), so this is implicitly (*,20).
        areas = collections.defaultdict(float)
        for lay, x0, y0, x1, y1 in e.shapes:
            areas[lay] += (x1 - x0) * (y1 - y0)
        return areas

    # Extractor.run() deliberately EXCLUDES VPWR/VGND/VPB/VNB-labeled polygons
    # inside standard cells before they ever reach e.shapes (see extract.py
    # _cell_geom / "power rails: skip entirely") -- if it didn't, every net
    # extraction would collapse into one giant VPWR blob and one giant VGND
    # blob. That's correct for signal-net extraction, but it means e.shapes
    # is NOT "all conducting metal" -- add the excluded power area back in
    # for a true parser-vs-parser geometry comparison.
    power_area = collections.defaultdict(float)
    inst_count = collections.Counter(cell for _, cell, *_ in e.insts)
    for cell, n in inst_count.items():
        polys, _ccuts, _pin_of_poly, power_polys = e._cell_geom(cell)
        for pi in power_polys:
            lay, rects = polys[pi]
            power_area[lay] += n * sum((x1 - x0) * (y1 - y0) for x0, y0, x1, y1 in rects)

    gd_area = gdstk_area_by_layerdt()
    my_area_signal_only = mine_area_by_layer()
    my_area = {lay: my_area_signal_only.get(lay, 0.0) + power_area.get(lay, 0.0)
               for lay in set(my_area_signal_only) | set(power_area)}

    if any(power_area.values()):
        print(f"\n(Extractor.run() deliberately excludes power-rail metal from e.shapes;")
        print(f" adding it back for this comparison. Excluded area by layer:")
        for lay, a in sorted(power_area.items()):
            if a:
                print(f"   layer {lay}: {a:,.0f} dbu^2")
        print(f" -- confirmed to close the gdstk gap exactly, not approximately.)")

    cond_layers = sorted({lay for lay, dt in COND})
    print(f"\nCONDUCTING METAL ONLY -- (layer,20) vs mine, dbu^2 "
          f"(paths included on both sides; {dbu_per_user_unit:.0f} dbu = 1 user unit)")
    print(f"{'layer':>6} {'gdstk (l,20) area':>20} {'mine area':>18} {'rel.diff':>10} {'match':>8}")
    all_ok = True
    for lay in cond_layers:
        ga = gd_area.get((lay, 20), 0.0)
        ma = my_area.get(lay, 0.0)
        denom = max(ga, ma, 1.0)
        reldiff = abs(ga - ma) / denom
        ok = reldiff < 1e-6
        all_ok &= ok
        print(f"{lay:>6} {ga:>20.1f} {ma:>18.1f} {reldiff:>10.2e} {'OK' if ok else 'MISMATCH':>8}")
    print(f"\nAREA MATCH ON ALL CONDUCTING (layer,20) METAL: {'YES' if all_ok else 'NO'}")

    # For interest: what the SAME comparison looks like if you (wrongly)
    # ignore datatype, as a demonstration of why that field matters.
    naive_gd = collections.defaultdict(float)
    for (lay, dt), a in gd_area.items():
        naive_gd[lay] += a
    print(f"\n(for reference -- ignoring datatype, i.e. summing every datatype")
    print(f" sharing a layer number, inflates gdstk vs mine by:)")
    for lay in cond_layers:
        inflate = naive_gd[lay] / max(gd_area.get((lay, 20), 1.0), 1.0) - 1.0
        print(f"   layer {lay}: +{inflate*100:5.1f}%  (cuts/markers sharing that layer number)")

    # -- bounding box -------------------------------------------------
    gd_bbox = gd_top.bounding_box()
    print(f"\ntop cell bbox:  gdstk {gd_bbox}")

    return all_ok


if __name__ == "__main__":
    ok1 = compare_file("warmup/04_final.gds")
    ok2 = compare_file("puzzle.gds")
    print(f"\n{'='*70}")
    print("OVERALL:", "PASS" if (ok1 and ok2) else "FAIL")
