# reimpl: the puzzle chip, rebuilt forwards

The rest of this repository goes **GDS → netlist → architecture**. This directory goes back
the other way: **architecture → RTL → GDS**, using the same open PDK the original was built
in, and checks the result against the original at every step.

The claim being tested is stronger than "I understood the chip." It is:

> Everything recovered in `UNDERSTANDING.md` Part V is complete and correct enough to
> **rebuild the chip from scratch** and have the rebuild behave identically.

It does. The re-implementation is bit-exact with the original on 18,943 cycles of
stimulus, including Jane Street's own `example_inputs.vcd`, at RTL, after synthesis,
and after place-and-route.

---

## Quick start

```bash
./run_all.sh          # RTL + synthesis + gate-level equivalence   (~2 min)
./run_all.sh --flow   # the above, then LibreLane to GDS           (~4 min)
./flow/sim_pnr.sh     # replay the vectors against the post-PnR netlist
python3 report.py     # compare the result against the original
```

Needs `iverilog`, `yosys`, the sky130A PDK (via `ciel`), and, for `--flow`, `nix`.

---

## What is here

| Path | What it is |
|---|---|
| `rtl/puzzle.v` | The design. Hand-written from the recovered architecture. |
| `rtl/region_map.v` | **Generated.** The 11×11 region lookup, transcribed from the map read off `puzzle.gds`. |
| `gen_regions.py` | Emits `region_map.v` from `tools/starbattle.REGIONS`. |
| `gen_vectors.py` | Emits golden vectors by **running the extracted netlist**. |
| `tb/tb_puzzle.v` | Replays those vectors against the DUT, cycle by cycle. |
| `tb/vectors.txt` | 17,498 cycles, 108 scenarios. |
| `tb/vectors_reset.txt` | 1,445 cycles: reset asserted mid-message, cut at every character. |
| `flow/synth.sh`, `flow/synth.ys` | Standalone yosys synthesis to sky130. |
| `flow/sim_pnr.sh` | Replays the vectors against the newest LibreLane post-PnR netlist. |
| `formal/solve.sh` | Runs the chip backwards: solves `success == 1` straight off the netlist. |
| `rtl/variants/puzzle_regout.v` | Variant matching the original's registered output byte (91 flops). |
| `flow/config.yaml` | LibreLane configuration. |
| `flow/config_diematch.yaml` | Comparison run: same RTL, floorplan pinned to the original's 200 x 300 um die. |
| `flow/pin_order.cfg` | Pin placement mirroring the original: inputs west, outputs east. |
| `report.py` | Side-by-side comparison with the original. |

Two files are generated rather than written, and that is the point: **the region map and
the golden vectors both come from `puzzle.gds` itself.** The RTL cannot quietly disagree
with the measurement, and the testbench's expectations are the real chip's behaviour
rather than my notes about it.

---

## The design

`rtl/puzzle.v` is an 11×11 Star Battle validator. 121 grid cells arrive one per clock on
`I`, row-major with the column advancing fastest. One clock after the last cell the verdict
lands on `success`, and `O[7:0]` emits an ASCII message one byte per clock.

```
                        ┌──────────────┐
    I ────┬────────────>│ 11 column    │──> col_ok[10:0]
          │             │   counters   │      (2 bits each, D fan-in 7)
          │             └──────────────┘
          ├────────────>┌──────────────┐
          │             │ 11 region    │──> reg_ok[10:0]
          │   region ──>│   counters   │      (2 bits each, D fan-in 11)
          │    map      └──────────────┘
          ├────────────>┌──────────────┐
          │             │ row counter  │──> row_bad   (sticky)
          │             │ + total      │──> total[7:0]
          │             └──────────────┘
          └────────────>┌──────────────┐
                        │ 12-deep      │──> adj_bad   (sticky)
                        │ window       │      taps at 1, 10, 11, 12
                        └──────────────┘
                                │
                         counts_ok / legal ──> success (latching)
                                │
                                └──────────> message generator ──> O[7:0]
```

Everything in it traces to a measurement:

- **Column counters have D fan-in 7, region counters 11.** The difference is exactly the
  four row-counter bits, because region membership is a 2-D lookup and column membership
  is not. That bimodality was the single most confusing fact in the whole project.
- **The adjacency window is 12 deep with taps at 1, 10, 11 and 12**: left, up-right, up,
  up-left. Only four of the eight neighbours, because a raster visits each touching pair
  once.
- **The verdict reads settled accumulator values**, gated by a registered `grid_done`
  rather than the combinational end-of-grid condition. That one pipeline stage is what puts
  the first character and `success` on the same clock, exactly as the original does. Getting
  this wrong shifts the whole message by one cycle, which is how I found it.
- **84 flip-flops.** The original has 92. Splitting both by when each flop moves: checker
  state 78 in each, message sequencer 6 in each, and an 8-bit **output byte register** the
  original has and this does not. See "Against the original" below.

### The five messages

The chip is a **diagnostic, not a pass/fail**, and the message set is symmetric:

| condition | message |
|---|---|
| a legal placement | `(* TWO STARS *)` |
| every count right, two stars touching | `TWO"NOT TOUCH` |
| no stars at all | `EMPTY SKY` |
| every cell a star | `BIG BANG` |
| anything else | `TRY AGAIN` |

`TWO"NOT TOUCH` is the one that probing never produces. It needs a placement correct in every
count and wrong only in adjacency. Of the 189 rectangle swaps of the solution, 23 qualify,
and random search essentially never lands on one. It came out of reading the logic.

`BIG BANG` fires on exactly one input out of 2^121, the completely full board. Feeding the
extracted netlist all ones reproduces it in a single line, and that is how the writeup
presents it, since all-zeros and all-ones are the two boards anyone tries first. In practice
it surfaced the other way round here, as the formal counterexample in `formal/`, which is
also what certifies that no sixth message is hiding.

`TWO"NOT TOUCH` is 13 bytes and byte 3 really is `0x22`, a double quote, presumably
`TWO "NOT TOUCH"` with the spacing lost. Reproduced verbatim.

---

## How it is verified

Golden vectors are produced by **simulating the netlist extracted from `puzzle.gds`**,
the same netlist that replays the vendor waveform 312/312 bit-exact. The testbench drives
the DUT with the recorded stimulus and compares `O[7:0]` and `success` every cycle.

The same testbench runs against three different DUTs:

| DUT | Result |
|---|---|
| `rtl/puzzle.v` | bit-exact, 18,943 cycles |
| `out/puzzle_synth.v` (yosys → sky130 gates) | bit-exact, 18,943 cycles |
| LibreLane post-PnR netlist | bit-exact, 18,943 cycles |

Scenario coverage in `vectors.txt`:

- the vendor's `example_inputs.vcd`, replayed exactly
- the unique legal placement, the empty board, single stars
- 25 single-star relocations
- 25 rectangle swaps. These preserve row and column counts *by construction*, so they
  isolate the region and adjacency rules from the counting rules
- 25 random 22-star placements

These are samples, sized to keep the vector file manageable. The exhaustive negative
sweeps live in `tools/verify_puzzle.py`: all 2,178 single-star relocations, all 189
rectangle swaps, and 200 random placements, every one of them rejected by the original.
- protocol edges: `enable` held low, `enable` stalling mid-grid, `enable` dropping during
  the message, bits past the 121st, a misaligned grid, back-to-back attempts
- 20 random attempts with random stalls

`vectors_reset.txt` covers asserting `rst_n` while a message is still emitting, cut at
every character position. Worth calling out: I initially assumed this was don't-care
behaviour, on the theory that the original's `dfxtp`/`dfstp` generator flops cannot be
cleared by reset. That was wrong. The divergence I was seeing was entirely the missing
`TWO"NOT TOUCH`; the original clears its generator perfectly cleanly. **Both vector sets are
required to pass.**

---

## Formal equivalence

Simulation shows agreement on the vectors I thought to write. `formal/prove.sh` proves it
for all of them at once: both designs are read into yosys, the extracted netlist with cell
behaviour taken from the PDK's own liberty file, driven from a single free input under a
protocol generated in hardware, and a SAT solver is asked whether any input sequence can make
their outputs differ.

```bash
./formal/solve.sh                         # solve the puzzle from the gates alone
./formal/prove.sh 145                     # success only, whole attempt
SUCCESS_ONLY=1 ./formal/prove.sh 145      # ditto, explicitly
TIE=0 SUCCESS_ONLY=1 ./formal/prove.sh 145  # with the floating net left free
./formal/prove.sh 100 free                # O and success, arbitrary stalls and resets
```

| Claim | Window | Result |
|---|---|---|
| `success` agrees for **every possible board** | 145 cycles | **proved**, 4 s |
| `success` agrees for **any value of the floating net** `n575` | 145 cycles | **proved**, 4 s |
| `O` and `success` agree for every board | 127 cycles | **proved**, 9 s |
| `O` and `success` agree for every board | 132 cycles | **proved**, 94 s |
| `O` and `success` agree for every board | **145 cycles, the whole attempt** | **proved**, 5 min |
| `O` and `success` agree under arbitrary stalls / mid-stream resets | 100 cycles | **proved**, 13 s |
| the same, across the full window | 145 cycles | no result after 30 min |

The 145-cycle `O` row is the strongest claim here: every output byte, on every board, across a
complete attempt. 2,049,750 variables and 5,359,575 clauses. It is worth recording that this
instance was intractable earlier in the project and only became solvable once the rebuild's
counters were fixed to saturate like the original's, which gave the solver far more internal
structure to match. The remaining gap is the free-control variant over the full window.

Two notes. `n575` is genuinely undriven in the original; the simulator treats it as 0, which
reproduces the vendor waveform exactly, and `TIE=1` pins it so SAT cannot manufacture a
mismatch from it. Leaving it free and comparing only `success` turns the earlier structural
argument ("its loads are outside the success cone") into a theorem.

And the solver finds `BIG BANG` on its own, which is what certifies the set is closed:
strip the fifth message out of the RTL and `./formal/prove.sh 145 free` returns the all-ones
board as a counterexample instead of a proof, in seconds, having never been told that 22 is
a meaningful number of stars.

---

## Results

Final run: `RUN_2026-08-16_11-26-16`, LibreLane 3.0.9, sky130A, 12 ns clock.

| Signoff check | Result |
|---|---|
| magic DRC | **0** |
| KLayout DRC | **0** |
| router DRC | **0** |
| LVS | **0** |
| antenna violations | **0** |
| setup, all 9 corners | **closed** (worst +0.137 ns, `max_ss_100C_1v60`) |
| hold, worst | **+0.028 ns** |
| max slew | 115 pins, slow corner only, see below |

The only outstanding item is max slew: 115 pins miss LibreLane's 0.75 ns transition
target in the slow corner, worst case **0.98 ns**. The PDK's own `max_transition` is
**1.5 ns**, so the design is well inside the foundry limit and misses a default set at
half of it. Typical and fast corners are clean. I tried `MAX_FANOUT_CONSTRAINT: 6` and
zeroed repair margins; neither moved the number, so it is documented rather than tuned
away. Roughly half the count is double-reporting: each inserted antenna diode adds a
second pin on the same net.

### Normalising the floorplan

The shipped run lets LibreLane pick the floorplan, which gives a near-square 126.0 x 136.8 um
die at 49% utilisation against the original's 200 x 300 um at 14%. That makes the two area
numbers hard to read, so `flow/config_diematch.yaml` re-runs the same RTL with the floorplan
pinned to the original's die:

| | original | shipped run | floorplan-matched |
|---|---|---|---|
| die area | 60,000 um^2 | 17,237 um^2 | **60,000 um^2** |
| standard-cell area | 8,417 um^2 | 6,466 um^2 | **8,260 um^2** |
| utilisation | 14.0% | 49.2% | **15.8%** |
| DRC / LVS / antenna | | 0 / 0 / 0 | 0 / 0 / 0 |
| post-PnR vs original | | bit-exact | bit-exact |

Given the same die to fill, the rebuild lands within 2% of the original's cell area and 1.8
points of its utilisation. That is the useful result. It is not the shipped configuration
because spreading the same logic over 3.5x the area costs a lot of buffering: 1,742 standard
cells against 758, and 408 max-slew violations against 115.

Not worth chasing further than that. Floorplanning sits downstream of everything this project
recovered, so layout appearance is not evidence about the logic. Two functionally identical
designs can look nothing alike. One flow note did come out of it: `RUN_FILL_INSERTION: false`,
tried to match the original's sparse die, fails with 1,238 magic DRC and 460 LVS errors,
because the fill cells carry well continuity.

### Against the original

| | original | re-implementation |
|---|---|---|
| logic / standard cells | 738 | 758 |
| flip-flops | 92 | 84 |
| standard-cell area | 8,417 µm² | 6,466 µm² |
| die area | 60,000 µm² (200 × 300) | 17,237 µm² |
| utilisation | 14.0% | 49.2% |
| tap / decap fillers | 880 | 2,136 |

The cell counts landing within a few percent of each other is a coincidence of two
offsetting differences, not a sign of a gate-for-gate match:

- **The re-implementation has 8 fewer flops**, and they are all one thing: the original
  **registers its output byte** and this does not. Eight flops, one per bit, four `dfstp`
  (set on reset) on `O[0] O[2] O[5] O[7]` and four `dfrtp` on the rest. Checker state (78)
  and message sequencer (6) match flop for flop; the original's 4-bit character index is
  reset-less (`dfxtp`), the only reset-less flops on the die.
  `rtl/variants/puzzle_regout.v` closes the gap: it decodes the next index and registers the
  byte, is bit-exact on all vectors, passes the same proofs, and synthesises to 91 flops.
  The 92nd is `O[7]`, which is 0 across all five messages, so yosys folds it away. It is not
  the shipped version because it misses slow-corner setup at every clock period tried.
- **It carries 51 timing-repair buffers and 29 clock buffers** that the original does not
  need, because I targeted a 12 ns clock and the original's target is unknown. Its clock
  tree is a single `clkbuf_16` feeding two levels, mine is sized for a constraint.

The original's die is 3.5× larger than needed at 14% utilisation, which is a deliberate
choice on Jane Street's part: it leaves room for the layer-200/0 Morse strip, the met2
logo, and the spatial separation between checker and generator that made the physical
clustering analysis work in the first place. A 49%-utilisation re-implementation is the
normal thing a flow produces when nobody asks it to leave space for jokes.

---

## Flow notes

Two things cost time and are worth writing down:

- **`VERILATOR_ROOT`.** A Homebrew verilator install exports it, and it shadows the one
  inside the nix closure, so LibreLane dies at the lint step with "VERILATOR_ROOT is set to
  inconsistent path". `run_all.sh` runs the flow under `env -u VERILATOR_ROOT`.
- **`pin_order.cfg` has no comment syntax.** `#` starts a direction directive (`#N`, `#E`,
  `#S`, `#W`), so a `# comment` line is parsed as an identifier and the flow fails with
  "identifier/regex '#' requires a direction to be set first".

And one that is a real lesson about the tools rather than a papercut:

- **The resizer only repairs the default corner unless it is told otherwise.** The first
  clean run had 128 max-slew violations, *all* of them in the slow corner and none in
  typical or fast. `RSZ_CORNERS` defaults to unset, meaning repair happens at
  `nom_tt_025C_1v80` alone. Adding `nom_ss_100C_1v60` to it is the fix. A signoff report
  that is clean at typical and dirty at slow is usually this, not a design problem.

`CLOCK_PERIOD: 12.0` is **our choice, not a recovered fact**. The original's target
frequency is unknown. At 10 ns the slow corner misses setup by ~0.3 ns. The critical path
is register → `total == 22` comparison → message decode → `O`, a register-to-output-port
path. It could be pipelined, and the original in fact does exactly that (see
`rtl/variants/puzzle_regout.v`), but registering the byte moves the counts-ok reduction in
front of the new flop and misses slow-corner setup at every period tried.
