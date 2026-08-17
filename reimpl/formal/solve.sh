#!/bin/sh
# Run the chip BACKWARDS: hand the solver the extracted netlist and the single
# constraint `success == 1`, and let it find a board that satisfies it.
#
# Nothing in the problem statement knows what Star Battle is. The only puzzle
# knowledge involved is whatever Jane Street compiled into the gates.
#
#   ./solve.sh            # find a winning board, print it, check it
set -e
cd "$(dirname "$0")/../.."
PDK_VER=$(ls -d "$HOME"/.ciel/ciel/sky130/versions/*/ | head -1)
LIB="${PDK_VER}sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib"
mkdir -p reimpl/out

yosys -q -l reimpl/out/solve.log -p "
  read_liberty -ignore_miss_func -ignore_miss_dir $LIB
  read_verilog out/puzzle_extracted.v
  rename puzzle gold
  cd gold; connect -set n575 1'b0; cd ..
  read_verilog reimpl/formal/harness_solve.v
  hierarchy -check -top harness_solve
  prep -top harness_solve -flatten
  memory_map; async2sync; techmap; opt -purge
  sat -seq 127 -set-init-zero -set-at 127 win 1 -dump_vcd reimpl/out/solve.vcd harness_solve
"

python3 - <<'PY'
import re, sys, os
sys.path.insert(0, os.path.abspath("."))
from tools.starbattle import solve
W = 11
vals = {}
for line in open("reimpl/out/solve.log"):
    m = re.match(r'\s*(\d+)\s+\\I\s+(\d+)\s', line)
    if m:
        vals[int(m.group(1))] = int(m.group(2))
board = [vals[t] for t in sorted(vals)][4:4 + W * W]
print(f"\nthe solver's board ({sum(board)} stars):\n")
for r in range(W):
    print("   " + " ".join("*" if board[r * W + c] else "." for c in range(W)))
sol = solve()[0]
ref = [1 if c in sol[r] else 0 for r in range(W) for c in range(W)]
print("\nmatches the Star Battle solution:", board == ref)
PY
