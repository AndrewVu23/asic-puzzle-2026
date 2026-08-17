// Formal equivalence harness.
//
// `gold` is the netlist extracted from puzzle.gds; `gate` is the re-implementation.
// Both are driven from the same free input `I`, under a protocol generated in
// hardware so that the SAT solver's only freedom is the board itself: reset is held
// for four cycles, then released, and the scan runs.
//
// `trigger` rises the moment the two disagree on any output. Proving trigger is
// unreachable for N cycles proves the designs agree for EVERY possible sequence of
// I over that window -- all 2^121 boards, not a sampled few thousand.

`default_nettype none

// With FREE_CONTROL defined, `enable` and `rst_n` are also free after the opening
// reset, so the proof additionally covers every possible stall pattern and every
// mid-stream or mid-message reset -- the cases the simulation vectors only sample.
module harness (
    input  wire clk,
    input  wire I,
`ifdef FREE_CONTROL
    input  wire rst_free,
    input  wire en_free,
`endif
    output wire trigger
);
    reg [7:0] t;
    initial t = 8'd0;
    always @(posedge clk)
        if (t != 8'hff) t <= t + 8'd1;

    // The opening reset is always applied: without it the two designs would start
    // from genuinely different states, since the original holds four set-on-reset
    // flops that the re-implementation has no counterpart for.
`ifdef FREE_CONTROL
    wire rst_n  = (t >= 8'd4) & rst_free;
    wire enable = en_free;
`else
    wire rst_n  = (t >= 8'd4);
    wire enable = 1'b1;
`endif

    wire [7:0] o_gold, o_gate;
    wire       s_gold, s_gate;

    gold u_gold (.clk(clk), .rst_n(rst_n), .enable(enable), .I(I),
                 .O(o_gold), .success(s_gold));
    gate u_gate (.clk(clk), .rst_n(rst_n), .enable(enable), .I(I),
                 .O(o_gate), .success(s_gate));

    // Only compare once reset has been released; before that the two designs are
    // legitimately in different states (the original holds four set-on-reset flops
    // the re-implementation does not have).
`ifdef SUCCESS_ONLY
    // Compare only the win condition. Used with the floating net left free, to prove
    // it cannot influence `success` no matter what value it takes.
    assign trigger = (t >= 8'd4) & (s_gold != s_gate);
`else
    assign trigger = (t >= 8'd4) & ((o_gold != o_gate) | (s_gold != s_gate));
`endif

endmodule

`default_nettype wire
