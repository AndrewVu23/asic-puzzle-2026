"""DEF reader: COMPONENTS + NETS pin lists. Used as ground truth for the warm-up."""
from __future__ import annotations
import re, collections

ORIENT = {"N", "S", "FN", "FS", "E", "W", "FE", "FW"}


def parse(path):
    txt = open(path).read()

    comps = {}
    m = re.search(r"^COMPONENTS\s+\d+\s*;(.*?)^END COMPONENTS", txt, re.S | re.M)
    if m:
        for ent in m.group(1).split(";"):
            ent = ent.strip()
            if not ent.startswith("-"):
                continue
            mm = re.match(r"-\s+(\S+)\s+(\S+).*?\(\s*(-?\d+)\s+(-?\d+)\s*\)\s+(\w+)\s*$",
                          ent.replace("\n", " "), re.S)
            if mm:
                nm, cell, x, y, o = mm.groups()
                comps[nm] = (cell, int(x), int(y), o)

    nets = {}
    m = re.search(r"^NETS\s+\d+\s*;(.*?)^END NETS", txt, re.S | re.M)
    if m:
        for ent in m.group(1).split(";"):
            ent = ent.strip()
            if not ent.startswith("-"):
                continue
            flat = ent.replace("\n", " ")
            head = flat.split("+")[0]
            nm = head.split()[1]
            conns = set()
            for a, b in re.findall(r"\(\s*(\S+)\s+(\S+)\s*\)", head):
                if a == "PIN":
                    conns.add(("__PORT__", b))
                else:
                    conns.add((a, b))
            nets[nm.replace("\\", "")] = conns
    return comps, nets


def def_to_gds_origin(x, y, orient, w, h):
    """DEF places the cell bbox lower-left at (x,y); GDS SREF stores the cell
    origin after transformation.  Returns (ox, oy, reflect, angle)."""
    if orient == "N":    return (x,     y,     False, 0.0)
    if orient == "FS":   return (x,     y + h, True,  0.0)
    if orient == "S":    return (x + w, y + h, False, 180.0)
    if orient == "FN":   return (x + w, y,     True,  180.0)
    raise ValueError(f"unhandled orientation {orient}")
