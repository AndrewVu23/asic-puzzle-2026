"""GDS -> gate-level netlist extraction for sky130 place-and-routed layouts.

Method
------
1. Flatten the top cell's hierarchy, classifying every SREF as either
   a standard-cell instance, a via/connector cell, or a plain container.
2. Reduce all geometry (BOUNDARY + PATH) to axis-aligned rectangles.
   sky130 P&R output is fully Manhattan, verified.
3. Union-find over rectangles:
      - same conducting layer + overlap/abut  -> same net
      - all conducting shapes inside one via-cell instance -> same net
   Every via cell in this PDK bridges exactly one adjacent layer pair, so
   rule 2 subsumes any hand-written layer-adjacency table.
4. Standard-cell signal pins are the li1 (67/20) polygons containing a
   67/5 TEXT label. Power pins (VPWR/VGND/VPB/VNB) are dropped.
5. Top-level ports are met3 (70/5) labels resolved against met3 geometry.
"""
from __future__ import annotations
import sys, collections
from tools.gdsread import Library, make_transform

# sky130 layer/datatype map ------------------------------------------------
LI1, MET1, MET2, MET3, MET4, MET5 = 67, 68, 69, 70, 71, 72
COND = {(LI1, 20), (MET1, 20), (MET2, 20), (MET3, 20), (MET4, 20), (MET5, 20)}
# cut layers that bridge two routing layers.  (66,44)=licon is deliberately
# EXCLUDED: it contacts poly/diff, and honouring it would short every cell
# through its own transistors.
CUTS = {(LI1, 44), (MET1, 44), (MET2, 44), (MET3, 44), (MET4, 44)}
CUT_BRIDGE = {LI1: (LI1, MET1), MET1: (MET1, MET2), MET2: (MET2, MET3),
              MET3: (MET3, MET4), MET4: (MET4, MET5)}
PIN_LABEL_DT = 5           # 67/5, 68/5, 70/5 ... text labels
POWER = {"VPWR", "VGND", "VPB", "VNB", "VDD", "VSS"}

Rect = tuple  # (layer, x0, y0, x1, y1)


# --- geometry -------------------------------------------------------------
def bbox(pts):
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def rectilinear_to_rects(pts):
    """Decompose a closed Manhattan ring into axis-aligned rectangles by
    horizontal slabs.  Exact for rectilinear polygons."""
    if len(pts) >= 2 and pts[0] == pts[-1]:
        pts = pts[:-1]
    n = len(pts)
    if n == 4:
        x0, y0, x1, y1 = bbox(pts)
        return [(x0, y0, x1, y1)]
    ys = sorted({p[1] for p in pts})
    out = []
    for ya, yb in zip(ys, ys[1:]):
        if yb <= ya:
            continue
        mid = (ya + yb) / 2.0
        xs = []
        for i in range(n):
            (xa, y1_), (xb, y2_) = pts[i], pts[(i + 1) % n]
            if xa == xb and min(y1_, y2_) < mid < max(y1_, y2_):
                xs.append(xa)
        xs.sort()
        for xa, xb in zip(xs[0::2], xs[1::2]):
            if xb > xa:
                out.append((xa, ya, xb, yb))
    return out


def path_to_rects(p):
    """Manhattan path with width -> rectangles, honouring PATHTYPE."""
    hw = p.width // 2
    pts = p.xy
    if len(pts) == 1:
        x, y = pts[0]
        return [(x - hw, y - hw, x + hw, y + hw)]
    if p.pathtype == 2:
        b = e = hw
    elif p.pathtype == 4:
        b, e = p.bgnextn, p.endextn
    elif p.pathtype == 1:            # round ends: approximate as square
        b = e = hw
    else:                            # 0 = flush
        b = e = 0
    out, last = [], len(pts) - 2
    for i, ((xa, ya), (xb, yb)) in enumerate(zip(pts, pts[1:])):
        sb = b if i == 0 else 0
        se = e if i == last else 0
        if ya == yb:                 # horizontal
            x0, x1 = (xa, xb) if xa <= xb else (xb, xa)
            if xa <= xb: x0 -= sb; x1 += se
            else:        x0 -= se; x1 += sb
            out.append((x0, ya - hw, x1, ya + hw))
        elif xa == xb:               # vertical
            y0, y1 = (ya, yb) if ya <= yb else (yb, ya)
            if ya <= yb: y0 -= sb; y1 += se
            else:        y0 -= se; y1 += sb
            out.append((xa - hw, y0, xa + hw, y1))
        else:                        # diagonal: fall back to bbox
            x0, x1 = sorted((xa, xb)); y0, y1 = sorted((ya, yb))
            out.append((x0 - hw, y0 - hw, x1 + hw, y1 + hw))
    return out


def xform_rect(f, r):
    x0, y0, x1, y1 = r
    a = f(x0, y0); b = f(x1, y1)
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))


# --- union-find -----------------------------------------------------------
class DSU:
    def __init__(self, n): self.p = list(range(n))
    def find(self, a):
        p = self.p
        while p[a] != a:
            p[a] = p[p[a]]; a = p[a]
        return a
    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb: self.p[rb] = ra


# --- extraction -----------------------------------------------------------
class Extractor:
    def __init__(self, gds, cell_prefix="sky130_", via_prefix="VIA_"):
        self.lib = Library(gds)
        self.cell_prefix = cell_prefix
        self.via_prefix = via_prefix
        tops = self.lib.top_cells()
        if len(tops) != 1:
            raise SystemExit(f"expected 1 top cell, got {tops}")
        self.topname = tops[0]
        self.shapes: list = []          # (layer, x0,y0,x1,y1)
        self.groups: list = []          # list of shape-index lists forced equal
        self.insts: list = []           # (instname, cellname, x, y, reflect, angle)
        self.pin_shapes: list = []      # (inst_idx, pinname, shape_idx)
        self.cuts: list = []            # (cutlayer, x0,y0,x1,y1)
        self.log = []

    # cell geometry, computed once per cell type
    def _cell_geom(self, cellname):
        """-> (polys, cuts, pin_of_poly, power_polys)

        polys : list of (layer, rects) -- EVERY conducting polygon in the cell,
                on every routing layer.  Standard cells are not li1-only: dfrtp_2
                and xor2_2 (among others) carry internal met1, and the router
                lands directly on that met1 with no li1->met1 via at all.
                Extracting li1 alone silently drops those connections.
        cuts  : list of (layer, rects) for mcon/via cuts inside the cell, which
                bridge the cell's own li1 to its own met1.
        """
        if not hasattr(self, "_geomcache"):
            self._geomcache = {}
        if cellname in self._geomcache:
            return self._geomcache[cellname]
        s = self.lib.structs[cellname]
        polys, cuts = [], []
        for b in s.boundaries:
            key = (b.layer, b.datatype)
            if key in COND:
                polys.append((b.layer, rectilinear_to_rects(b.xy)))
            elif key in CUTS:
                cuts.append((b.layer, rectilinear_to_rects(b.xy)))
        for p in s.paths:
            if (p.layer, p.datatype) in COND:
                polys.append((p.layer, path_to_rects(p)))

        pin_of_poly, power_polys = {}, set()
        for t in s.texts:
            if t.texttype != PIN_LABEL_DT:
                continue
            for pi, (lay, rects) in enumerate(polys):
                if lay != t.layer:
                    continue
                if any(x0 <= t.x <= x1 and y0 <= t.y <= y1 for x0, y0, x1, y1 in rects):
                    if t.string in POWER:
                        power_polys.add(pi)
                    else:
                        pin_of_poly.setdefault(pi, t.string)
                    break
        for pi in power_polys:
            pin_of_poly.pop(pi, None)
        self._geomcache[cellname] = (polys, cuts, pin_of_poly, power_polys)
        return self._geomcache[cellname]

    def _add(self, layer, r):
        self.shapes.append((layer,) + tuple(r))
        return len(self.shapes) - 1

    def _walk(self, structname, f, path, depth=0):
        s = self.lib.structs[structname]
        local = []
        for b in s.boundaries:
            if (b.layer, b.datatype) in COND:
                for r in rectilinear_to_rects(b.xy):
                    local.append(self._add(b.layer, xform_rect(f, r)))
            elif (b.layer, b.datatype) in CUTS:
                for r in rectilinear_to_rects(b.xy):
                    self.cuts.append((b.layer,) + xform_rect(f, r))
        for p in s.paths:
            if (p.layer, p.datatype) in COND:
                for r in path_to_rects(p):
                    local.append(self._add(p.layer, xform_rect(f, r)))
        for sr in s.srefs:
            for ci in range(max(sr.cols, 1)):
                for ri in range(max(sr.rows, 1)):
                    ox = sr.x + ci * sr.cvec[0] + ri * sr.rvec[0]
                    oy = sr.y + ci * sr.cvec[1] + ri * sr.rvec[1]
                    ax, ay = f(ox, oy)
                    bx, by = f(0, 0)
                    ex, ey = f(1, 0); fx, fy = f(0, 1)
                    m = (ex - bx, ey - by, fx - bx, fy - by)
                    inner = make_transform(0, 0, sr.reflect, sr.angle, sr.mag)

                    def g(px, py, ax=ax, ay=ay, m=m, inner=inner):
                        ix, iy = inner(px, py)
                        return (int(round(ax + ix * m[0] + iy * m[2])),
                                int(round(ay + ix * m[1] + iy * m[3])))

                    nm = f"{path}/{sr.sname}@{ox},{oy}" if path else f"{sr.sname}@{ox},{oy}"
                    if sr.sname.startswith(self.via_prefix):
                        idx = self._walk(sr.sname, g, nm, depth + 1)
                        if len(idx) > 1:
                            self.groups.append(idx)     # via bridges its layers
                        local.extend(idx)
                    elif sr.sname.startswith(self.cell_prefix):
                        ii = len(self.insts)
                        self.insts.append((nm, sr.sname, ox, oy, sr.reflect, sr.angle))
                        polys, ccuts, pin_of_poly, power_polys = self._cell_geom(sr.sname)
                        for pi, (lay, rects) in enumerate(polys):
                            if pi in power_polys:
                                continue          # power rails: skip entirely
                            grp = []
                            for r in rects:
                                si = self._add(lay, xform_rect(g, r))
                                grp.append(si); local.append(si)
                            if len(grp) > 1:
                                self.groups.append(grp)   # one polygon = one node
                            pin = pin_of_poly.get(pi)
                            if pin is not None:
                                self.pin_shapes.append((ii, pin, grp[0]))
                        for lay, rects in ccuts:
                            for r in rects:
                                self.cuts.append((lay,) + xform_rect(g, r))
                    else:
                        local.extend(self._walk(sr.sname, g, nm, depth + 1))
        return local

    def run(self, grid=2000):
        top = self.lib.structs[self.topname]
        ident = make_transform(0, 0, False, 0.0, 1.0)
        self._walk(self.topname, ident, "")
        n = len(self.shapes)
        self.log.append(f"shapes={n} instances={len(self.insts)} pinshapes={len(self.pin_shapes)}")

        dsu = DSU(n)
        for g in self.groups:
            for k in g[1:]:
                dsu.union(g[0], k)

        # spatial hash per layer
        buckets = collections.defaultdict(list)
        for i, (lay, x0, y0, x1, y1) in enumerate(self.shapes):
            for gx in range(x0 // grid, x1 // grid + 1):
                for gy in range(y0 // grid, y1 // grid + 1):
                    buckets[(lay, gx, gy)].append(i)
        checked = set()
        for key, idxs in buckets.items():
            if len(idxs) < 2:
                continue
            for a in range(len(idxs)):
                ia = idxs[a]; _, ax0, ay0, ax1, ay1 = self.shapes[ia]
                for b in range(a + 1, len(idxs)):
                    ib = idxs[b]
                    pk = (ia, ib) if ia < ib else (ib, ia)
                    if pk in checked:
                        continue
                    checked.add(pk)
                    _, bx0, by0, bx1, by1 = self.shapes[ib]
                    if ax0 <= bx1 and bx0 <= ax1 and ay0 <= by1 and by0 <= ay1:
                        dsu.union(ia, ib)

        # cut layers bridge adjacent routing layers.  This is what actually
        # connects a cell's own li1 pin to its own internal met1, and what makes
        # top-level via geometry work without special-casing via cell names.
        bridged = 0
        for (clay, cx0, cy0, cx1, cy1) in self.cuts:
            pair = CUT_BRIDGE.get(clay)
            if pair is None:
                continue
            hits = []
            for lay in pair:
                for gx in range(cx0 // grid, cx1 // grid + 1):
                    for gy in range(cy0 // grid, cy1 // grid + 1):
                        for i in buckets.get((lay, gx, gy), ()):
                            _, x0, y0, x1, y1 = self.shapes[i]
                            if x0 <= cx1 and cx0 <= x1 and y0 <= cy1 and cy0 <= y1:
                                hits.append(i)
            if len(hits) > 1:
                for k in hits[1:]:
                    dsu.union(hits[0], k)
                bridged += 1
        self.log.append(f"cuts={len(self.cuts)} bridging={bridged}")
        self.dsu = dsu

        # nets
        self.net_of_shape = [dsu.find(i) for i in range(n)]
        self.pins_by_net = collections.defaultdict(set)
        for ii, pin, si in self.pin_shapes:
            self.pins_by_net[self.net_of_shape[si]].add((ii, pin))
        self.log.append(f"nets_with_pins={len(self.pins_by_net)}")
        return self

    def port_labels(self):
        """Map top-level TEXT labels to net roots."""
        top = self.lib.structs[self.topname]
        out = {}
        for t in top.texts:
            if t.texttype != PIN_LABEL_DT or t.string in POWER:
                continue
            hits = [i for i, (lay, x0, y0, x1, y1) in enumerate(self.shapes)
                    if lay == t.layer and x0 <= t.x <= x1 and y0 <= t.y <= y1]
            if hits:
                out[t.string] = self.net_of_shape[hits[0]]
            else:
                self.log.append(f"WARN port {t.string} label not on any {t.layer} shape")
        return out

    def power_nets(self):
        """Nets touching a cell power rail, identified structurally."""
        roots = set()
        for cellname in {c for _, c, *_ in self.insts}:
            pass
        # power rails were excluded from pin extraction; find them by the
        # met4/met5 straps carrying VPWR/VGND top labels instead
        top = self.lib.structs[self.topname]
        for t in top.texts:
            if t.string in POWER:
                for i, (lay, x0, y0, x1, y1) in enumerate(self.shapes):
                    if lay == t.layer and x0 <= t.x <= x1 and y0 <= t.y <= y1:
                        roots.add(self.net_of_shape[i]); break
        return roots
