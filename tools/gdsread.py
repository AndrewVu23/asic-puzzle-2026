"""Minimal, dependency-free GDSII reader.

Enough of the format to handle place-and-routed standard-cell layouts:
BOUNDARY / PATH / SREF / AREF / TEXT, with STRANS/ANGLE/MAG transforms.
"""
from __future__ import annotations
import struct, math
from dataclasses import dataclass, field

# --- record types we care about -------------------------------------------
HEADER,BGNLIB,LIBNAME,UNITS,ENDLIB = 0x0002,0x0102,0x0206,0x0305,0x0400
BGNSTR,STRNAME,ENDSTR              = 0x0502,0x0606,0x0700
BOUNDARY,PATH,SREF,AREF,TEXT       = 0x0800,0x0900,0x0A00,0x0B00,0x0C00
LAYER,DATATYPE,WIDTH,XY,ENDEL      = 0x0D02,0x0E02,0x0F03,0x1003,0x1100
SNAME,COLROW,TEXTTYPE,PRESENTATION = 0x1206,0x1302,0x1602,0x1701
STRING,STRANS,MAG,ANGLE,PATHTYPE   = 0x1906,0x1A01,0x1B05,0x1C05,0x2102
BGNEXTN,ENDEXTN                    = 0x3003,0x3103


def _f64(b: bytes) -> float:
    """GDSII 8-byte excess-64 base-16 float."""
    sign = -1.0 if b[0] & 0x80 else 1.0
    exp = (b[0] & 0x7F) - 64
    mant = int.from_bytes(b[1:8], "big") / float(1 << 56)
    return sign * mant * (16.0 ** exp)


@dataclass
class Boundary:
    layer: int
    datatype: int
    xy: list           # [(x,y), ...] closed ring, integer DB units

@dataclass
class Path:
    layer: int
    datatype: int
    width: int
    pathtype: int
    xy: list
    bgnextn: int = 0
    endextn: int = 0

@dataclass
class Sref:
    sname: str
    x: int
    y: int
    reflect: bool = False   # mirror about x-axis BEFORE rotation
    angle: float = 0.0      # degrees, CCW
    mag: float = 1.0
    cols: int = 1           # AREF
    rows: int = 1
    cvec: tuple = (0, 0)    # per-column step
    rvec: tuple = (0, 0)    # per-row step

@dataclass
class Text:
    layer: int
    texttype: int
    x: int
    y: int
    string: str

@dataclass
class Structure:
    name: str
    boundaries: list = field(default_factory=list)
    paths: list = field(default_factory=list)
    srefs: list = field(default_factory=list)
    texts: list = field(default_factory=list)


class Library:
    def __init__(self, path):
        self.name = ""
        self.unit_user = 1e-3       # user units per db unit
        self.unit_meters = 1e-9     # meters per db unit
        self.structs: dict[str, Structure] = {}
        self._parse(path)

    # -- parsing ----------------------------------------------------------
    def _records(self, path):
        with open(path, "rb") as fh:
            data = fh.read()
        i, n = 0, len(data)
        while i < n - 3:
            ln, rt = struct.unpack(">HH", data[i:i + 4])
            if ln < 4:
                break
            yield rt, data[i + 4:i + ln]
            i += ln

    def _parse(self, path):
        cur = None
        el = None          # ('boundary'|'path'|'sref'|'aref'|'text', dict)
        for rt, body in self._records(path):
            if rt == LIBNAME:
                self.name = body.split(b"\0")[0].decode("ascii", "replace")
            elif rt == UNITS:
                self.unit_user = _f64(body[0:8])
                self.unit_meters = _f64(body[8:16])
            elif rt == STRNAME:
                nm = body.split(b"\0")[0].decode("ascii", "replace")
                cur = Structure(nm)
                self.structs[nm] = cur
            elif rt == ENDSTR:
                cur = None
            elif rt == BOUNDARY:
                el = ("boundary", {})
            elif rt == PATH:
                el = ("path", {"width": 0, "pathtype": 0, "bgnextn": 0, "endextn": 0})
            elif rt == SREF:
                el = ("sref", {})
            elif rt == AREF:
                el = ("aref", {})
            elif rt == TEXT:
                el = ("text", {})
            elif el is not None and rt == LAYER:
                el[1]["layer"] = struct.unpack(">h", body[:2])[0]
            elif el is not None and rt == DATATYPE:
                el[1]["datatype"] = struct.unpack(">h", body[:2])[0]
            elif el is not None and rt == TEXTTYPE:
                el[1]["texttype"] = struct.unpack(">h", body[:2])[0]
            elif el is not None and rt == WIDTH:
                el[1]["width"] = struct.unpack(">i", body[:4])[0]
            elif el is not None and rt == BGNEXTN:
                el[1]["bgnextn"] = struct.unpack(">i", body[:4])[0]
            elif el is not None and rt == ENDEXTN:
                el[1]["endextn"] = struct.unpack(">i", body[:4])[0]
            elif el is not None and rt == PATHTYPE:
                el[1]["pathtype"] = struct.unpack(">h", body[:2])[0]
            elif el is not None and rt == SNAME:
                el[1]["sname"] = body.split(b"\0")[0].decode("ascii", "replace")
            elif el is not None and rt == STRING:
                el[1]["string"] = body.split(b"\0")[0].decode("ascii", "replace")
            elif el is not None and rt == STRANS:
                flags = struct.unpack(">H", body[:2])[0]
                el[1]["reflect"] = bool(flags & 0x8000)
            elif el is not None and rt == ANGLE:
                el[1]["angle"] = _f64(body[:8])
            elif el is not None and rt == MAG:
                el[1]["mag"] = _f64(body[:8])
            elif el is not None and rt == COLROW:
                c, r = struct.unpack(">hh", body[:4])
                el[1]["cols"], el[1]["rows"] = c, r
            elif el is not None and rt == XY:
                cnt = len(body) // 8
                pts = [struct.unpack(">ii", body[8 * k:8 * k + 8]) for k in range(cnt)]
                el[1]["xy"] = pts
            elif rt == ENDEL:
                if el is not None and cur is not None:
                    self._finish(cur, el)
                el = None

    @staticmethod
    def _finish(cur: Structure, el):
        kind, d = el
        if kind == "boundary":
            cur.boundaries.append(Boundary(d.get("layer", -1), d.get("datatype", -1), d["xy"]))
        elif kind == "path":
            cur.paths.append(Path(d.get("layer", -1), d.get("datatype", -1),
                                  d.get("width", 0), d.get("pathtype", 0), d["xy"],
                                  d.get("bgnextn", 0), d.get("endextn", 0)))
        elif kind == "sref":
            x, y = d["xy"][0]
            cur.srefs.append(Sref(d["sname"], x, y, d.get("reflect", False),
                                  d.get("angle", 0.0), d.get("mag", 1.0)))
        elif kind == "aref":
            # AREF xy = [origin, col-end, row-end]
            pts = d["xy"]
            org = pts[0]
            cols = d.get("cols", 1); rows = d.get("rows", 1)
            cvec = ((pts[1][0] - org[0]) // max(cols, 1), (pts[1][1] - org[1]) // max(cols, 1))
            rvec = ((pts[2][0] - org[0]) // max(rows, 1), (pts[2][1] - org[1]) // max(rows, 1))
            cur.srefs.append(Sref(d["sname"], org[0], org[1], d.get("reflect", False),
                                  d.get("angle", 0.0), d.get("mag", 1.0),
                                  cols, rows, cvec, rvec))
        elif kind == "text":
            x, y = d["xy"][0]
            cur.texts.append(Text(d.get("layer", -1), d.get("texttype", 0), x, y,
                                  d.get("string", "")))

    # -- hierarchy --------------------------------------------------------
    def top_cells(self):
        referenced = set()
        for s in self.structs.values():
            for r in s.srefs:
                referenced.add(r.sname)
        return [n for n in self.structs if n not in referenced]


def make_transform(x, y, reflect, angle, mag=1.0):
    """Return f(px,py) -> (X,Y) applying GDSII placement semantics:
    reflect about x-axis, then magnify, then rotate CCW, then translate."""
    a = math.radians(angle or 0.0)
    ca, sa = math.cos(a), math.sin(a)
    if abs(ca) < 1e-12: ca = 0.0
    if abs(sa) < 1e-12: sa = 0.0
    m = mag or 1.0
    sy = -1.0 if reflect else 1.0

    def f(px, py):
        qx = px * m
        qy = py * sy * m
        return (int(round(x + qx * ca - qy * sa)),
                int(round(y + qx * sa + qy * ca)))
    return f


def compose(outer, inner_sref):
    """Transform for a cell placed by inner_sref inside a frame given by `outer`."""
    ox, oy = outer(inner_sref.x, inner_sref.y)
    # derive outer's linear part by probing
    bx, by = outer(0, 0)
    ex, ey = outer(1, 0)
    fx, fy = outer(0, 1)
    ax1, ax2 = ex - bx, ey - by      # image of unit-x
    ay1, ay2 = fx - bx, fy - by      # image of unit-y
    inner = make_transform(0, 0, inner_sref.reflect, inner_sref.angle, inner_sref.mag)

    def f(px, py):
        ix, iy = inner(px, py)
        return (int(round(ox + ix * ax1 + iy * ay1)),
                int(round(oy + ix * ax2 + iy * ay2)))
    return f
