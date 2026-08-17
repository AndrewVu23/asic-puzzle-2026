"""The non-circuit content of puzzle.gds: a Morse message and a logo.

`INTERNAL_3` and `INTERNAL_7` are each a single rectangle on layer 200/0 -- not a
real sky130 layer, so nothing in the flow ever looks at them. Both are 2720 DB units
tall; `INTERNAL_3` is 1380 wide and `INTERNAL_7` is 4140, exactly 3x. All 36
placements sit on one horizontal line at y = -52720, below the die area.

Two element widths in a 1:3 ratio, on a line, with gaps of 1, 3 and 7 units, is
Morse: dot / dash, intra-character / inter-character / inter-word spacing.

Separately, every top-level met2 (69/20) boundary in the file -- all 1366 of them --
is a 300 x 300 nm square on a 300 nm pitch, forming a 57 x 57 pixel bitmap of the Jane
Street logo at (43.45, 43.75) um. Unlike the Morse marks it is on a real routing layer,
so it is genuinely manufactured: three electrically isolated islands of met2 floating
over a region that contains only tap fillers. They carry no pins, so the union-find
groups them as three pinless conductor nets and the netlist never sees them -- the same
category as the 1882 standard-cell internal nodes. Nothing is special-cased.

It is unrelated to n575, the undriven net: ~130 um away, different layers, no pins.

Run:  python3 -m tools.eggs
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


WIDTH = {"INTERNAL_3": 1380, "INTERNAL_7": 4140}   # dot, dash
UNIT = 1380

MORSE = {
    ".-": "A", "-...": "B", "-.-.": "C", "-..": "D", ".": "E", "..-.": "F",
    "--.": "G", "....": "H", "..": "I", ".---": "J", "-.-": "K", ".-..": "L",
    "--": "M", "-.": "N", "---": "O", ".--.": "P", "--.-": "Q", ".-.": "R",
    "...": "S", "-": "T", "..-": "U", "...-": "V", ".--": "W", "-..-": "X",
    "-.--": "Y", "--..": "Z", "-----": "0", ".----": "1", "..---": "2",
    "...--": "3", "....-": "4", ".....": "5", "-....": "6", "--...": "7",
    "---..": "8", "----.": "9",
}


def bars(gds=None):
    """-> sorted [(x_start, x_end, structure_name)] for the layer-200/0 stamps."""
    from tools.gdsread import Library
    lib = Library(gds or _p("puzzle.gds"))
    top = lib.structs[lib.top_cells()[0]]
    for n, w in WIDTH.items():
        b = lib.structs[n].boundaries[0]
        xs = [p[0] for p in b.xy]
        assert (b.layer, b.datatype) == (200, 0) and max(xs) - min(xs) == w
    return sorted((s.x, s.x + WIDTH[s.sname], s.sname)
                  for s in top.srefs if s.sname in WIDTH)


def morse(marks):
    """Bar geometry -> morse string, using run lengths in units of UNIT."""
    out = []
    for i, (a, b, _) in enumerate(marks):
        if i:
            gap = (a - marks[i - 1][1]) // UNIT
            out.append("" if gap == 1 else " " if gap == 3 else " / ")
        out.append("." if (b - a) // UNIT == 1 else "-")
    return "".join(out)


def decode(s):
    return "".join(" " if w == "/" else MORSE.get(w, f"[{w}]") for w in s.split(" "))


def render(marks, scale=UNIT):
    """ASCII picture of the bar strip, one character per unit."""
    x0 = marks[0][0]
    row = []
    for a, b, _ in marks:
        col = (a - x0) // scale
        row += [" "] * (col - len(row))
        row += ["#"] * ((b - a) // scale)
    return "".join(row)


LOGO_PIXEL = 300


def logo(gds=None):
    """-> (pixels, origin, pitch) for the top-level met2 bitmap."""
    from tools.gdsread import Library
    lib = Library(gds or _p("puzzle.gds"))
    top = lib.structs[lib.top_cells()[0]]
    px = [(min(p[0] for p in b.xy), min(p[1] for p in b.xy))
          for b in top.boundaries if (b.layer, b.datatype) == (69, 20)]
    assert px, "no top-level met2 found"
    x0, y0 = min(x for x, _ in px), min(y for _, y in px)
    return px, (x0, y0), LOGO_PIXEL


def render_logo(px, origin, pitch, on="#", off="."):
    x0, y0 = origin
    w = (max(x for x, _ in px) - x0) // pitch + 1
    h = (max(y for _, y in px) - y0) // pitch + 1
    g = [[off] * w for _ in range(h)]
    for x, y in px:
        g[(y - y0) // pitch][(x - x0) // pitch] = on
    return "\n".join("".join(r) for r in reversed(g))


def main():
    m = bars()
    counts = {n: sum(1 for _, _, s in m if s == n) for n in WIDTH}
    print(f"{len(m)} stamps on layer 200/0 at y=-52720: {counts}")
    print(f"element widths: {sorted({(b - a) // UNIT for a, b, _ in m})} units "
          f"(unit = {UNIT / 1000} um)")
    gaps = sorted({(m[i][0] - m[i - 1][1]) // UNIT for i in range(1, len(m))})
    print(f"gap widths:     {gaps} units  -> morse intra/inter-character/word\n")
    strip = render(m)
    for i in range(0, len(strip), 100):
        print("  " + strip[i:i + 100])
    s = morse(m)
    print(f"\nmorse:  {s}")
    print(f"decodes to:  {decode(s)!r}")
    assert decode(s) == "PER ARENAM AD ASTRA"
    print("\n'through the sand to the stars' -- per aspera ad astra, with arena = sand.")

    px, origin, pitch = logo()
    print(f"\n{len(px)} met2 squares of {pitch} nm at "
          f"({origin[0] / 1000:.2f}, {origin[1] / 1000:.2f}) um -- the logo bitmap:\n")
    print(render_logo(px, origin, pitch))


if __name__ == "__main__":
    main()
