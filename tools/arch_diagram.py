"""Emit the recovered architecture as an SVG block diagram.

Two variants:
  architecture-checker.svg   what section 5 has established: the checker only, with
                             the generator left as a closed box. Shows nothing about
                             the five messages.
  architecture.svg           the full picture for section 8, including the four
                             selectors the generator actually needs.

Every box and annotation traces to a measurement in Part V: flop counts, D fan-in
widths, the window depth and its taps, and the one-way checker/generator split.
"""
import io, os, sys

FULL = "--checker-only" not in sys.argv

W, H = 1520, 830
INK, MUTE, LINE, THIN = "#0f172a", "#64748b", "#334155", "#94a3b8"
ROSE, ROSE_E = "#fde8ef", "#e0748f"
BLUE, BLUE_E = "#e0effa", "#6ba7d0"
GOLD, GOLD_E = "#fdf6dd", "#cfb75c"
GREY, GREY_E = "#eef2f7", "#a8b4c4"
MONO = ' font-family="ui-monospace,SFMono-Regular,Menlo,monospace"'

BUS, ACC_Y, ACC_H, ACC_W = 104, 252, 132, 218
XS = [268, 522, 776, 1030, 1284]
RED_Y, OK_Y, SUC_Y, GEN_Y = 416, 486, 546, 630
CX = [x + ACC_W / 2 for x in XS]
DROP = [x + 34 for x in XS]                 # I enters near each box's left edge
MID = 700

o = []
def box(x, y, w, h, fill, edge, lines, size=13):
    o.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="{fill}" '
             f'stroke="{edge}" stroke-width="1.7"/>')
    y0 = y + h / 2 - (len(lines) - 1) * (size + 3) / 2 + size / 3
    for i, t in enumerate(lines):
        o.append(f'<text x="{x+w/2}" y="{y0+i*(size+3)}" '
                 f'font-size="{size if i==0 else size-1.8}" '
                 f'font-weight="{"600" if i==0 else "400"}" text-anchor="middle" '
                 f'fill="{INK if i==0 else MUTE}">{t}</text>')

def path(pts, arrow=True, dash=False, col=LINE, wid=1.8):
    d = "M " + " L ".join(f"{x} {y}" for x, y in pts)
    a = ' marker-end="url(#a)"' if arrow else ""
    ds = ' stroke-dasharray="6 5"' if dash else ""
    o.append(f'<path d="{d}" fill="none" stroke="{col}" stroke-width="{wid}"{ds}{a}/>')

def txt(x, y, t, size=12, col=INK, anchor="middle", weight="400", mono=False):
    o.append(f'<text x="{x}" y="{y}" font-size="{size}" text-anchor="{anchor}" '
             f'fill="{col}" font-weight="{weight}"{MONO if mono else ""}>{t}</text>')

o.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
         f'viewBox="0 0 {W} {H}" font-family="ui-sans-serif,Helvetica,Arial">'
         f'<rect width="{W}" height="{H}" fill="#fff"/>'
         f'<defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6.5" '
         f'markerHeight="6.5" orient="auto"><path d="M 0 0 L 10 5 L 0 10 z" fill="{LINE}"/>'
         f'</marker><marker id="g" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6.5" '
         f'markerHeight="6.5" orient="auto"><path d="M 0 0 L 10 5 L 0 10 z" fill="{THIN}"/>'
         f'</marker></defs>')

txt(24, 36, "The recovered architecture", 18, INK, "start", "600")
txt(24, 58, "11 x 11 Star Battle validator. 121 cells arrive one per clock on I, row-major, "
            "column advancing fastest.", 12.5, MUTE, "start")

# ---- I bus --------------------------------------------------------------------
txt(26, BUS + 6, "I", 16, INK, "start", "600", mono=True)
txt(42, BUS - 10, "1 bit per clock", 10.5, MUTE, "start")
o.append(f'<path d="M 42 {BUS} L {DROP[-1]} {BUS}" stroke="{LINE}" stroke-width="2.2" fill="none"/>')
for x in DROP:
    path([(x, BUS), (x, ACC_Y)])

# ---- addressing: position counters, then the region map -----------------------
box(24, 150, 186, 78, GREY, GREY_E, ["row[3:0], col[3:0]", "raster position", "8 flops"])
box(XS[1] + 64, 150, 226, 78, BLUE, BLUE_E,
    ["11 x 11 REGION MAP", "(row, col) -> region id", "flop-free lookup"])
path([(210, 189), (XS[1] + 64, 189)], dash=True, col=THIN)
o.append(f'<path d="M 210 189 L {XS[1]+64} 189" fill="none" stroke="{THIN}" '
         f'stroke-width="1.8" stroke-dasharray="6 5" marker-end="url(#g)"/>')
path([(110, 228), (110, 292), (XS[0], 292)], dash=True, col=THIN)
txt(116, 286, "col", 10.5, MUTE, "start", mono=True)
path([(XS[1] + 177, 228), (XS[1] + 177, 240), (CX[1], 240), (CX[1], ACC_Y)])
txt(XS[1] + 190, 224, "selects one of the 11", 10, MUTE, "start")

# ---- the five accumulators ----------------------------------------------------
for x, (t, sub) in zip(XS, [
    ("11 COLUMN counters", ["2 bits each, saturating", "D fan-in 7", "addressed by col only"]),
    ("11 REGION counters", ["2 bits each, saturating", "D fan-in 11", "addressed by col AND row"]),
    ("ROW counter",  ["2 bits, reused each row", "checked at end of line", "result latched sticky"]),
    ("TOTAL counter", ["8 bits", "every star on", "the whole board"]),
    ("ADJACENCY window", ["12-deep delay line", "D fan-in 3", "taps 1, 10, 11, 12"])]):
    box(x, ACC_Y, ACC_W, ACC_H, ROSE, ROSE_E, [t] + sub)

for cx, r, s in zip(CX, ["all == 2", "all == 2", "~row_bad", "== 22", "~adj_bad"],
                    ["", "", "sticky", "", "sticky"]):
    path([(cx, ACC_Y + ACC_H), (cx, RED_Y - 15)])
    txt(cx, RED_Y, r, 13.5, INK, "middle", "600", mono=True)
    if s:
        txt(cx, RED_Y + 15, s, 9.5, MUTE)

# ---- counts_ok, then success --------------------------------------------------
for cx in CX[:4]:
    path([(cx, RED_Y + 26), (cx, OK_Y)], arrow=False)
o.append(f'<path d="M {CX[0]} {OK_Y} L {CX[3]} {OK_Y}" stroke="{LINE}" stroke-width="1.8" fill="none"/>')
txt(MID, OK_Y - 9, "counts_ok   =   the four counting rules", 13, INK, "middle", "600", mono=True)
path([(MID, OK_Y), (MID, SUC_Y - 17)])
box(MID - 108, SUC_Y - 17, 216, 44, "#fff", LINE, ["success"], 15)
txt(MID, SUC_Y + 40, "latching:  counts_ok AND ~adj_bad", 11, MUTE)
path([(CX[4], RED_Y + 26), (CX[4], SUC_Y + 5), (MID + 108, SUC_Y + 5)])

# ---- one-way split ------------------------------------------------------------
o.append(f'<path d="M 24 {SUC_Y+58} L {W-24} {SUC_Y+58}" stroke="#cbd5e1" stroke-width="1.2" '
         f'stroke-dasharray="8 6" fill="none"/>')
txt(28, SUC_Y + 74, "CHECKER above,  GENERATOR below.  Measured: the success cone sits wholly "
                    "inside the O cone and nothing is success-only, so information crosses "
                    "this line once and never returns.", 11, MUTE, "start")

# ---- generator, with everything it actually needs -----------------------------
box(MID - 175, GEN_Y, 350, 108, GOLD, GOLD_E,
    ["MESSAGE GENERATOR", "4-bit character index, no reset", "8-bit output register",
     "5 sequencer + 8 output flops"] if FULL else
    ["MESSAGE GENERATOR", "229 cells, 13 flops", "reads checker state,", "never feeds it"])
path([(MID, SUC_Y + 27), (MID, GEN_Y)])
# the extra selectors, tapped on the left and brought into the generator
if FULL:
    path([(430, OK_Y), (430, GEN_Y + 40), (MID - 175, GEN_Y + 40)], col=LINE)
    txt(424, GEN_Y + 30, "counts_ok", 11.5, INK, "end", "600", mono=True)
    path([(CX[3], RED_Y + 26), (CX[3], 600), (452, 600), (452, GEN_Y + 76),
          (MID - 175, GEN_Y + 76)], col=LINE)
    txt(424, GEN_Y + 80, "total", 11.5, INK, "end", "600", mono=True)
    path([(CX[4], 600), (1180, 600), (1180, GEN_Y + 32), (MID + 175, GEN_Y + 32)], col=LINE)
    txt(1188, GEN_Y + 24, "adj_bad", 11.5, INK, "start", "600", mono=True)
    txt(424, GEN_Y + 96, "success alone is one bit. Five messages", 10, MUTE, "end")
    txt(424, GEN_Y + 109, "need four separate selectors.", 10, MUTE, "end")
OY = GEN_Y + (80 if FULL else 54)
path([(MID + 175, OY), (MID + 300, OY)])
txt(MID + 308, OY + 4, "O[7:0]", 15, INK, "start", "600", mono=True)

txt(24, H - 20,
    "78 checker  +  1 success  +  5 sequencer  +  8 output register   =   92" if FULL
    else "79 flops in the success cone   +   13 in the generator   =   92", 13,
    INK, "start", "600", mono=True)
o.append("</svg>")

out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "architecture.svg" if FULL else "architecture-checker.svg")
io.open(out, "w").write("\n".join(o))
print("wrote", out)
