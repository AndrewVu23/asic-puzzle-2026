#!/bin/sh
# Replay the golden vectors against the LibreLane post-PnR netlist.
# Run after ./run_all.sh --flow; picks up the newest run.
set -e
cd "$(dirname "$0")/.."
PDK_VER=$(ls -d "$HOME"/.ciel/ciel/sky130/versions/*/ | head -1)
MODELS="${PDK_VER}sky130A/libs.ref/sky130_fd_sc_hd/verilog"
NL=$(ls -d flow/runs/RUN_* | tail -1)/final/nl/puzzle.nl.v
echo "netlist: $NL"
for v in vectors vectors_reset; do
    iverilog -g2012 -DFUNCTIONAL -DUNIT_DELAY="#0" -DVECTORS="\"tb/$v.txt\"" \
        -o "out/sim_pnr_$v" tb/tb_puzzle.v "$NL" \
        "$MODELS/primitives.v" "$MODELS/sky130_fd_sc_hd.v"
    printf '%-16s ' "$v"
    "./out/sim_pnr_$v" | grep RESULT
done
