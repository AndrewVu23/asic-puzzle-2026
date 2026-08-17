#!/bin/sh
# Synthesise the re-implementation with yosys against the ciel-installed sky130A PDK.
set -e
cd "$(dirname "$0")/.."
PDK_VER=$(ls -d "$HOME"/.ciel/ciel/sky130/versions/*/ | head -1)
LIBERTY="${PDK_VER}sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib"
[ -f "$LIBERTY" ] || { echo "liberty not found: $LIBERTY"; exit 1; }
mkdir -p out
yosys -q -p "read_liberty -lib $LIBERTY" 2>/dev/null || true
LIBERTY="$LIBERTY" yosys -l out/synth.log -D LIBERTY -p "
  read_verilog rtl/region_map.v rtl/puzzle.v
  hierarchy -check -top puzzle
  proc; opt; fsm; opt; memory; opt; techmap; opt
  dfflibmap -liberty $LIBERTY
  abc -liberty $LIBERTY
  setundef -zero
  opt_clean -purge
  write_verilog -noattr out/puzzle_synth.v
  stat -liberty $LIBERTY
"
echo "wrote out/puzzle_synth.v"
