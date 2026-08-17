#!/bin/sh
# Rebuild everything: regenerate the region map and golden vectors from puzzle.gds,
# check the RTL against them, synthesise, check the gate netlist against the same
# vectors, and run the full RTL-to-GDS flow.
#
#   ./run_all.sh          RTL + synthesis + gate-level checks   (~2 min)
#   ./run_all.sh --flow   the above, then LibreLane to GDS      (~4 min)
set -e
cd "$(dirname "$0")"
mkdir -p out

PDK_VER=$(ls -d "$HOME"/.ciel/ciel/sky130/versions/*/ | head -1)
MODELS="${PDK_VER}sky130A/libs.ref/sky130_fd_sc_hd/verilog"

say() { printf '\n=== %s ===\n' "$1"; }

say "regenerating region map and golden vectors from puzzle.gds"
python3 gen_regions.py
python3 gen_vectors.py

say "RTL vs extracted netlist"
for v in vectors vectors_reset; do
    iverilog -g2012 -DVECTORS="\"tb/$v.txt\"" -o "out/sim_rtl_$v" \
        tb/tb_puzzle.v rtl/puzzle.v rtl/region_map.v
    printf '%-16s ' "$v"
    "./out/sim_rtl_$v" | grep RESULT
done

say "synthesis"
./flow/synth.sh >/dev/null
grep -E "Chip area for top" out/synth.log

say "post-synthesis gate-level vs extracted netlist"
for v in vectors vectors_reset; do
    iverilog -g2012 -DFUNCTIONAL -DUNIT_DELAY="#0" -DVECTORS="\"tb/$v.txt\"" \
        -o "out/sim_gl_$v" tb/tb_puzzle.v out/puzzle_synth.v \
        "$MODELS/primitives.v" "$MODELS/sky130_fd_sc_hd.v"
    printf '%-16s ' "$v"
    "./out/sim_gl_$v" | grep RESULT
done

say "formal equivalence (success condition, all 2^121 boards)"
SUCCESS_ONLY=1 ./formal/prove.sh 145 2>&1 | grep -E "SUCCESS!|FAIL" || echo "  (see out/formal_*.log)"

if [ "$1" = "--flow" ]; then
    say "LibreLane RTL-to-GDS"
    # VERILATOR_ROOT from a system install shadows the one inside the nix closure.
    env -u VERILATOR_ROOT nix run 'github:librelane/librelane' -- flow/config.yaml
    python3 report.py
fi

say "done"
