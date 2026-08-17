"""Levelised gate-level simulator for extracted sky130 netlists."""
from __future__ import annotations
import collections
from tools import cells
from tools.netlist import Netlist, base_cell, OUTPUT_PINS


class Sim:
    def __init__(self, nl: Netlist):
        self.nl = nl
        self.comb, self.flops, self.ties = [], [], []
        for li, (_, cell, *_ ) in enumerate(nl.insts):
            b = base_cell(cell)
            if b in cells.SEQUENTIAL:
                self.flops.append(li)
            elif b == "conb":
                self.ties.append(li)
            elif b in cells.PHYSICAL:
                pass
            else:
                self.comb.append(li)
        self.fn = {li: cells.combinational(base_cell(nl.insts[li][1]))
                   for li in self.comb}
        self.base = {li: base_cell(nl.insts[li][1]) for li in range(len(nl.insts))}

        # net -> driving instance
        self.drv = {}
        for li in range(len(nl.insts)):
            for pin, net in nl.conns[li].items():
                if pin in OUTPUT_PINS:
                    self.drv[net] = li

        # topological order over combinational instances
        deps = {li: set() for li in self.comb}
        for li in self.comb:
            for pin, net in nl.conns[li].items():
                if pin in OUTPUT_PINS:
                    continue
                d = self.drv.get(net)
                if d is not None and d in deps:
                    deps[li].add(d)
        order, seen, temp = [], set(), set()
        self.loops = []

        def visit(u):
            if u in seen:
                return
            if u in temp:
                self.loops.append(u); return
            temp.add(u)
            for v in deps[u]:
                visit(v)
            temp.discard(u); seen.add(u); order.append(u)

        for li in self.comb:
            visit(li)
        self.order = order
        self.state = {li: False for li in self.flops}
        self.v = {}

    # -- evaluation -------------------------------------------------------
    def _q_pin(self, li):
        return "Q"

    def settle(self, inputs):
        v = self.v
        v.clear()
        v.update(inputs)
        nl = self.nl
        for li in self.ties:
            for pin, net in nl.conns[li].items():
                if pin == "HI": v[net] = True
                elif pin == "LO": v[net] = False
        for _ in range(3):
            for li in self.flops:
                q = nl.conns[li].get("Q")
                if q is not None:
                    v[q] = self.state[li]
            for li in self.order:
                c = nl.conns[li]
                args = {pin: v.get(net, False) for pin, net in c.items()
                        if pin not in OUTPUT_PINS}
                try:
                    out = self.fn[li](args)
                except Exception:
                    out = {}
                for pin, val in out.items():
                    net = c.get(pin)
                    if net is not None:
                        v[net] = val
            # asynchronous set/reset takes effect without a clock edge
            changed = False
            for li in self.flops:
                spec = cells.SEQUENTIAL[self.base[li]]
                rp = spec.get("rst")
                if rp is None:
                    continue
                net = nl.conns[li].get(rp)
                if net is not None and not v.get(net, True):
                    if self.state[li] != bool(spec["rst_val"]):
                        self.state[li] = bool(spec["rst_val"]); changed = True
            if not changed:
                break
        return v

    def cycle(self, inputs, clk_port="clk"):
        """One full clock period: low phase, rising edge, high phase."""
        nl = self.nl
        lo = dict(inputs); lo[nl.ports[clk_port]] = False
        self.settle(lo)
        clk_lo = {li: self.v.get(nl.conns[li].get("CLK"), False) for li in self.flops}

        hi = dict(inputs); hi[nl.ports[clk_port]] = True
        self.settle(hi)
        d = {}
        for li in self.flops:
            spec = cells.SEQUENTIAL[self.base[li]]
            clk_hi = self.v.get(nl.conns[li].get("CLK"), False)
            if clk_hi and not clk_lo[li]:
                d[li] = self.v.get(nl.conns[li].get(spec["d"]), False)
        for li, val in d.items():
            spec = cells.SEQUENTIAL[self.base[li]]
            rp = spec.get("rst")
            net = nl.conns[li].get(rp) if rp else None
            if net is not None and not self.v.get(net, True):
                continue                     # async reset dominates
            self.state[li] = val
        self.settle(hi)
        return self.v

    # -- convenience ------------------------------------------------------
    def port(self, name):
        return self.v.get(self.nl.ports[name], False)

    def reset_state(self):
        for li in self.flops:
            self.state[li] = False

    def make_inputs(self, **vals):
        return {self.nl.ports[k]: bool(x) for k, x in vals.items()
                if k in self.nl.ports}
