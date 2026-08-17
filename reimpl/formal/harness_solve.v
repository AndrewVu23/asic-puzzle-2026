// Run the extracted chip BACKWARDS: hand the solver the netlist and the single
// constraint `success == 1`, and let it find a board that satisfies it.
//
// Nothing here knows what Star Battle is. The only puzzle knowledge in the whole
// problem is whatever Jane Street compiled into the gates.
`default_nettype none

module harness_solve (input wire clk, input wire I, output wire win);
    reg [7:0] t;
    initial t = 8'd0;
    always @(posedge clk) if (t != 8'hff) t <= t + 8'd1;

    wire rst_n = (t >= 8'd4);          // 4 cycles of reset, then the 121-cell scan
    wire [7:0] o; wire s;

    gold u_gold (.clk(clk), .rst_n(rst_n), .enable(1'b1), .I(I),
                 .O(o), .success(s));

    assign win = s;
endmodule
`default_nettype wire
