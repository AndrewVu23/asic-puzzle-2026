#!/bin/sh
# Formal equivalence between the netlist extracted from puzzle.gds and the
# re-implementation, by bounded model checking.
#
#   ./prove.sh [cycles] [free]
#
#     cycles   how many clock cycles to prove over. 145 covers a whole attempt:
#              4 reset + 121 grid cells + the longest message.
#     free     also leave `enable` and `rst_n` unconstrained after the opening
#              reset, so the proof covers every stall pattern and every mid-stream
#              or mid-message reset.
#
#   TIE=0            leave the undriven net n575 free instead of tying it to 0.
#   SUCCESS_ONLY=1   compare only `success`, not the output bytes.
#
# n575 is genuinely undriven in Jane Street's design. The simulator treats it as 0,
# which reproduces their own waveform exactly. Left free, SAT will happily pick a
# value for it and manufacture a mismatch on O -- so the honest pair of runs is:
#
#   TIE=1                      -> full equivalence on O and success
#   TIE=0 SUCCESS_ONLY=1       -> success agrees for ANY value of the floating net
set -e
cd "$(dirname "$0")/../.."

N="${1:-30}"
FREE=""
[ "$2" = "free" ] && FREE="-DFREE_CONTROL"
TIE="${TIE:-1}"
ONLY=""
[ "$SUCCESS_ONLY" = "1" ] && ONLY="-DSUCCESS_ONLY"

PDK_VER=$(ls -d "$HOME"/.ciel/ciel/sky130/versions/*/ | head -1)
LIB="${PDK_VER}sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib"
mkdir -p reimpl/out
LOG="reimpl/out/formal_${N}${2}_tie${TIE}${SUCCESS_ONLY}.log"

if [ "$TIE" = "1" ]; then
    TIECMD="cd gold; connect -set n575 1'b0; cd .."
else
    TIECMD=""
fi

yosys -l "$LOG" -p "
  read_liberty -ignore_miss_func -ignore_miss_dir $LIB
  read_verilog out/puzzle_extracted.v
  rename puzzle gold
  $TIECMD

  read_verilog reimpl/rtl/region_map.v reimpl/rtl/puzzle.v
  rename puzzle gate

  read_verilog $FREE $ONLY reimpl/formal/harness.v
  hierarchy -check -top harness
  prep -top harness -flatten
  memory_map
  async2sync
  techmap
  opt -purge
  sat -verify -prove trigger 0 -seq $N -set-init-zero harness
"
echo "log: $LOG"
