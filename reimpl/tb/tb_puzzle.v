// -----------------------------------------------------------------------------
// tb_puzzle.v -- replays golden vectors taken from the EXTRACTED netlist.
//
// The reference is not hand-written expectations; it is the behaviour of the
// netlist recovered from puzzle.gds, which itself replays Jane Street's own
// waveform 312/312 bit-exact. So a pass here means the re-implementation matches
// the real chip.
//
// The same testbench drives the RTL and the post-synthesis netlist; only the
// source file compiled alongside it changes.
//
//   iverilog -g2012 -o sim tb/tb_puzzle.v rtl/puzzle.v -I rtl
// -----------------------------------------------------------------------------

`timescale 1ns / 1ps
`default_nettype none

module tb_puzzle;

    localparam integer MAXV    = 40000;
    localparam integer MAXSHOW = 12;          // stop printing after this many failures

    reg  [11:0] vec [0:MAXV-1];
    integer     nvec, i, errors, checks;
    reg  [11:0] v;

    reg         clk = 1'b0;
    reg         rst_n, enable, I;
    wire [7:0]  O;
    wire        success;

    reg  [7:0]  exp_O;
    reg         exp_success;

    puzzle dut (
        .clk     (clk),
        .rst_n   (rst_n),
        .enable  (enable),
        .I       (I),
        .O       (O),
        .success (success)
    );

    always #5 clk = ~clk;

    // Count the vectors actually present: $readmemb leaves the tail as x.
    task count_vectors;
        begin
            nvec = 0;
            while (nvec < MAXV && vec[nvec] !== 12'bx) nvec = nvec + 1;
        end
    endtask

    initial begin
        for (i = 0; i < MAXV; i = i + 1) vec[i] = 12'bx;
        $readmemb(`VECTORS, vec);
        count_vectors;

        if (nvec == 0) begin
            $display("FATAL: no vectors loaded from %0s", `VECTORS);
            $finish;
        end

        errors = 0;
        checks = 0;
        rst_n  = 1'b0;
        enable = 1'b0;
        I      = 1'b0;

        for (i = 0; i < nvec; i = i + 1) begin
            v = vec[i];
            @(negedge clk);
            rst_n       = v[11];
            enable      = v[10];
            I           = v[9];
            exp_O       = v[8:1];
            exp_success = v[0];

            @(posedge clk);
            #1;                       // let the edge settle, then sample
            checks = checks + 1;
            if (O !== exp_O || success !== exp_success) begin
                errors = errors + 1;
                if (errors <= MAXSHOW)
                    $display("MISMATCH cycle %0d: in(rst_n=%b enable=%b I=%b)  got(O=%02h success=%b)  want(O=%02h success=%b)",
                             i, rst_n, enable, I, O, success, exp_O, exp_success);
                else if (errors == MAXSHOW + 1)
                    $display("... further mismatches suppressed");
            end
        end

        $display("");
        $display("checked %0d cycles against the extracted netlist", checks);
        if (errors == 0)
            $display("RESULT: PASS -- bit-exact on O[7:0] and success");
        else
            $display("RESULT: FAIL -- %0d mismatching cycles", errors);
        $display("");
`ifdef REPORT_ONLY
        $display("(REPORT_ONLY: divergence measured, not treated as failure)");
`else
        if (errors != 0) $fatal(1);
`endif
        $finish;
    end

    // Decode the emitted messages, so a passing run is also readable.
    integer nmsg = 0;
    always @(posedge clk) begin
        if (O !== 8'h00 && O !== 8'hxx) begin
            if (O >= 8'h20 && O < 8'h7f) $write("%c", O);
            nmsg = nmsg + 1;
        end
    end

endmodule

`default_nettype wire
