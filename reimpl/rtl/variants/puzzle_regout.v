// VARIANT: registered output byte.
//
// The original chip registers O: eight flops, one per output bit, four `dfstp`
// (set on reset, driving O[0] O[2] O[5] O[7]) and four `dfrtp` (O[1] O[3] O[4]
// O[6]). rtl/puzzle.v drives O combinationally instead, which is the entire
// 84-vs-92 flop gap.
//
// This file closes that gap. It decodes the NEXT character index and registers
// the byte, which keeps O cycle-identical while matching the original's
// structure. It is bit-exact on all 18,943 vectors and passes the same formal
// equivalence proofs, and it synthesises to 91 flops. The 92nd is O[7], which is
// provably 0 for all five messages, so yosys removes it here and the original's
// flow did not.
//
// It is not the shipped version, because selecting on the combinational `legal`
// rather than the registered `success` puts the whole counts_ok reduction tree in
// front of the output register. That path does not close setup in the slow corner
// at any clock period tried (12.0, 13.0, 13.5 ns); the delivered delay tracks the
// target, so the constraint is not the lever.
//
// -----------------------------------------------------------------------------
// puzzle.v -- an 11x11 Star Battle validator
//
// A forward re-implementation of the Jane Street 2026 ASIC puzzle, written from
// the architecture recovered out of puzzle.gds. See UNDERSTANDING.md Part V for
// how each fact below was measured rather than guessed.
//
// Protocol
//   Hold rst_n low to arm. With enable high, present the 121 grid cells on I,
//   one per clock, row-major with the column advancing fastest. One clock after
//   the 121st cell the verdict lands on `success` and O begins emitting the
//   message, one ASCII byte per clock, O = 0 at all other times.
//
//   Placement is legal when every row, every column and every region holds
//   exactly two stars, and no two stars touch -- diagonals included.
//
//   Message      "(* TWO STARS *)"  a legal placement
//                "TWO\"NOT TOUCH"    every count correct, but two stars touch
//                "EMPTY SKY"        no stars at all
//                "BIG BANG"         every cell a star
//                "TRY AGAIN"        anything else
//
//   The chip is a diagnostic, not just a pass/fail: getting all three counting
//   rules right and only the touching rule wrong earns its own message.
//
//   `enable` stalls the scan; the message emits regardless of it once the grid
//   has been consumed. `success` latches until reset.
//
// Timing note. `grid_done` registers the end of the scan, and it is that flag --
// not the combinational end-of-grid condition -- that gates the verdict and
// starts the generator. So every check below reads settled accumulator values.
// This one pipeline stage is what places the first character and `success` on
// the same clock, exactly as the original does.
// -----------------------------------------------------------------------------

`default_nettype none

module puzzle (
    input  wire       clk,
    input  wire       rst_n,     // asynchronous, active low
    input  wire       enable,    // advance the scan
    input  wire       I,         // one grid cell per clock
    output wire [7:0] O,         // ASCII message, one byte per clock
    output reg        success
);

    localparam integer W     = 11;    // grid is W x W
    localparam [1:0]   STARS = 2'd2;  // per row, per column, per region
    localparam [7:0]   TOTAL = 8'd22; // = W * STARS

    // ---------------------------------------------------------------- scan
    reg  [3:0] col, row;
    reg        grid_done;                     // all 121 cells consumed
    wire       step    = enable & ~grid_done;
    wire       eol     = (col == W - 1);      // last cell of a row
    wire       eog     = eol & (row == W - 1);// last cell of the grid
    wire       hit     = step & I;            // a star is being absorbed now
    wire       eog_now = step & eog;

    always @(posedge clk or negedge rst_n)
        if (!rst_n) begin
            col <= 4'd0;
            row <= 4'd0;
        end else if (step) begin
            col <= eol ? 4'd0 : col + 4'd1;
            if (eol) row <= row + 4'd1;
        end

    always @(posedge clk or negedge rst_n)
        if (!rst_n)       grid_done <= 1'b0;
        else if (eog_now) grid_done <= 1'b1;

    // ------------------------------------------------------- region lookup
    // The one irreducibly design-specific part: an 11x11 constant map. This is
    // the large flop-free combinational block in the original layout.
    wire [3:0] rgn;
    region_map u_regions (.row(row), .col(col), .rgn(rgn));

    // -------------------------------------------------- per-column counters
    // D fan-in 7 in the original: two own bits + four column-counter bits + step.
    wire [W-1:0] col_ok;
    genvar g;
    generate
        for (g = 0; g < W; g = g + 1) begin : COLUMN
            reg  [1:0] cnt;
            wire       inc = hit & (col == g);
            always @(posedge clk or negedge rst_n)
                if (!rst_n)                   cnt <= 2'd0;
                else if (inc && cnt != 2'd3)  cnt <= cnt + 2'd1;   // saturates
            assign col_ok[g] = (cnt == STARS);
        end
    endgenerate

    // -------------------------------------------------- per-region counters
    // D fan-in 11: the same, plus the four row-counter bits. Needing the row as
    // well as the column is exactly what makes a region a region.
    wire [W-1:0] reg_ok;
    generate
        for (g = 0; g < W; g = g + 1) begin : REGION
            reg  [1:0] cnt;
            wire       inc = hit & (rgn == g);
            always @(posedge clk or negedge rst_n)
                if (!rst_n)                   cnt <= 2'd0;
                else if (inc && cnt != 2'd3)  cnt <= cnt + 2'd1;   // saturates
            assign reg_ok[g] = (cnt == STARS);
        end
    endgenerate

    // ------------------------------------------------------- per-row counter
    // Rows are contiguous in a raster scan, so one counter plus a sticky fault
    // flag suffices -- no need for eleven of them.
    //
    // All three star counters saturate at 3 rather than wrapping, exactly as the
    // original does. Two bits can only tell 0, 1, 2 and "more than 2" apart, which
    // is all the rule ever asks; saturating is what makes "3" mean "too many"
    // instead of aliasing back to a legal count.
    reg  [1:0] rowcnt;
    reg        row_bad;
    wire [1:0] rowcnt_n = (hit && rowcnt != 2'd3) ? rowcnt + 2'd1 : rowcnt;

    always @(posedge clk or negedge rst_n)
        if (!rst_n) begin
            rowcnt  <= 2'd0;
            row_bad <= 1'b0;
        end else if (step) begin
            rowcnt <= eol ? 2'd0 : rowcnt_n;
            if (eol) row_bad <= row_bad | (rowcnt_n != STARS);
        end

    // ------------------------------------------------------ total star count
    reg [7:0] total;
    always @(posedge clk or negedge rst_n)
        if (!rst_n) total <= 8'd0;
        else        total <= total + {7'd0, hit};

    // ---------------------------------------------------------- adjacency
    // A 12-deep sliding window gives the four neighbours already visited by the
    // raster: left, and the three above. Symmetry makes the other four
    // redundant -- every touching pair is caught exactly once.
    //
    //            c-1    c    c+1
    //     r-1     12    11    10     <- this many cells ago
    //     r        1     *
    //
    reg  [11:0] win;
    reg         adj_bad;
    wire        nb_left = (col != 0)     & win[0];
    wire        nb_upr  = (col != W - 1) & win[9];
    wire        nb_up   =                  win[10];
    wire        nb_upl  = (col != 0)     & win[11];

    always @(posedge clk or negedge rst_n)
        if (!rst_n) begin
            win     <= 12'd0;
            adj_bad <= 1'b0;
        end else if (step) begin
            win     <= {win[10:0], I};
            adj_bad <= adj_bad | (hit & (nb_left | nb_upr | nb_up | nb_upl));
        end

    // ------------------------------------------------------------- verdict
    // Counts and adjacency are kept apart so the generator can distinguish
    // "you counted right but two stars touch" from a general failure.
    wire counts_ok = (&col_ok) & (&reg_ok) & ~row_bad & (total == TOTAL);
    wire legal     = counts_ok & ~adj_bad;

    always @(posedge clk or negedge rst_n)
        if (!rst_n)                 success <= 1'b0;
        else if (grid_done & legal) success <= 1'b1;

    // --------------------------------------------------- message generator
    // Reads checker state and never feeds it -- the one-way split visible in the
    // original as the success cone sitting wholly inside the O cone.
    reg  [3:0] chidx;
    reg        emitting, emitted;
    wire       empty = (total == 8'd0);          // an empty sky
    wire       full  = (total == 8'd121);         // every cell a star
    wire       touch = counts_ok & adj_bad;       // right counts, stars touching
    wire [3:0] lastch = legal   ? 4'd14 :         // "(* TWO STARS *)"   15
                        touch   ? 4'd12 :         // "TWO\"NOT TOUCH"    13
                        full    ? 4'd7  : 4'd8;   // "BIG BANG" 8, others 9

    // Once `grid_done` sets, `step` drops and every counter freezes, so `legal`,
    // `touch`, `full` and `empty` hold still for the whole message. The generator
    // can therefore select on them directly.
    wire       start = grid_done & ~emitted;
    wire [3:0] nidx  = start                            ? 4'd0
                     : (emitting && chidx != lastch)    ? chidx + 4'd1
                     :                                    chidx;
    wire       nemit = start                            ? 1'b1
                     : (emitting && chidx == lastch)    ? 1'b0
                     :                                    emitting;

    always @(posedge clk or negedge rst_n)
        if (!rst_n) begin
            emitting <= 1'b0;
            emitted  <= 1'b0;
            chidx    <= 4'd0;
        end else begin
            emitting <= nemit;
            chidx    <= nidx;
            if (start) emitted <= 1'b1;
        end

    reg [7:0] ch;
    always @* begin
        if (legal)      // "(* TWO STARS *)"
            case (nidx)
                4'd0: ch = "("; 4'd1: ch = "*"; 4'd2: ch = " "; 4'd3: ch = "T";
                4'd4: ch = "W"; 4'd5: ch = "O"; 4'd6: ch = " "; 4'd7: ch = "S";
                4'd8: ch = "T"; 4'd9: ch = "A"; 4'd10: ch = "R"; 4'd11: ch = "S";
                4'd12: ch = " "; 4'd13: ch = "*"; default: ch = ")";
            endcase
        else if (touch)  // "TWO\"NOT TOUCH"
            case (nidx)
                4'd0: ch = "T"; 4'd1: ch = "W"; 4'd2: ch = "O"; 4'd3: ch = 8'h22;
                4'd4: ch = "N"; 4'd5: ch = "O"; 4'd6: ch = "T"; 4'd7: ch = " ";
                4'd8: ch = "T"; 4'd9: ch = "O"; 4'd10: ch = "U"; 4'd11: ch = "C";
                default: ch = "H";
            endcase
        else if (full)  // "BIG BANG"
            case (nidx)
                4'd0: ch = "B"; 4'd1: ch = "I"; 4'd2: ch = "G"; 4'd3: ch = " ";
                4'd4: ch = "B"; 4'd5: ch = "A"; 4'd6: ch = "N";
                default: ch = "G";
            endcase
        else if (empty) // "EMPTY SKY"
            case (nidx)
                4'd0: ch = "E"; 4'd1: ch = "M"; 4'd2: ch = "P"; 4'd3: ch = "T";
                4'd4: ch = "Y"; 4'd5: ch = " "; 4'd6: ch = "S"; 4'd7: ch = "K";
                default: ch = "Y";
            endcase
        else            // "TRY AGAIN"
            case (nidx)
                4'd0: ch = "T"; 4'd1: ch = "R"; 4'd2: ch = "Y"; 4'd3: ch = " ";
                4'd4: ch = "A"; 4'd5: ch = "G"; 4'd6: ch = "A"; 4'd7: ch = "I";
                default: ch = "N";
            endcase
    end

    // The original registers its output byte: eight flops, one per bit, four of
    // them `dfstp` (set on reset) and four `dfrtp`. Decoding the next index and
    // registering it keeps the byte cycle-identical while matching that structure.
    reg [7:0] o_reg;
    always @(posedge clk or negedge rst_n)
        if (!rst_n) o_reg <= 8'h00;
        else        o_reg <= nemit ? ch : 8'h00;

    assign O = o_reg;

endmodule

`default_nettype wire
