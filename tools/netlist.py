"""Turn extracted connectivity into a named netlist + Verilog."""
from __future__ import annotations
import collections, re
from tools.extract import Extractor

OUTPUT_PINS = {"X", "Y", "Q", "Q_N", "COUT", "SUM", "HI", "LO"}
FILLER = ("tapvpwrvgnd", "decap", "fill", "tap_", "__tap")


def base_cell(cell):
    return re.sub(r"_\d+$", "", cell.split("__")[1])


class Netlist:
    def __init__(self, gds, in_ports, out_ports):
        self.e = Extractor(gds).run()
        e = self.e
        self.power = e.power_nets()
        self.ports = e.port_labels()          # name -> net root
        self.in_ports = list(in_ports)
        self.out_ports = list(out_ports)

        # instances (drop physical-only fillers)
        self.insts = []                       # (name, cell, x, y, reflect, angle)
        self.keep = []                        # index into e.insts
        for i, rec in enumerate(e.insts):
            if any(f in rec[1] for f in FILLER):
                continue
            self.keep.append(i)
            self.insts.append(rec)
        self.idx_of = {gi: li for li, gi in enumerate(self.keep)}

        # net naming
        self.net_name = {}
        for p, n in self.ports.items():
            self.net_name[n] = p
        k = 0
        self.conns = collections.defaultdict(dict)   # local inst -> {pin: net}
        self.net_pins = collections.defaultdict(set)
        for net, pins in e.pins_by_net.items():
            if net in self.power:
                continue
            if net not in self.net_name:
                self.net_name[net] = f"n{k}"; k += 1
            for gi, pin in pins:
                if gi in self.idx_of:
                    li = self.idx_of[gi]
                    self.conns[li][pin] = net
                    self.net_pins[net].add((li, pin))

        self.inst_name = [f"U{i}_{base_cell(c)}" for i, (_, c, *_) in enumerate(self.insts)]

    # -- queries ----------------------------------------------------------
    def driver_of(self, net):
        for li, pin in self.net_pins.get(net, ()):
            if pin in OUTPUT_PINS:
                return (li, pin)
        return None

    def loads_of(self, net):
        return [(li, pin) for li, pin in self.net_pins.get(net, ()) if pin not in OUTPUT_PINS]

    def cell_hist(self):
        return collections.Counter(base_cell(c) for _, c, *_ in self.insts)

    # -- emit -------------------------------------------------------------
    def verilog(self, module="puzzle"):
        L = []
        bus = collections.defaultdict(list)
        scalars = []
        for p in self.in_ports + self.out_ports:
            m = re.match(r"(\w+)\[(\d+)\]$", p)
            if m: bus[m.group(1)].append(int(m.group(2)))
            else: scalars.append(p)
        decl = list(scalars) + sorted(bus)
        L.append(f"module {module} ({', '.join(decl)});")
        for p in self.in_ports:
            if "[" not in p: L.append(f"  input {p};")
        for b in sorted(bus):
            hi = max(bus[b])
            direction = "output" if any(f"{b}[" in q for q in self.out_ports) else "input"
            L.append(f"  {direction} [{hi}:0] {b};")
        for p in self.out_ports:
            if "[" not in p: L.append(f"  output {p};")
        wires = sorted({v for v in self.net_name.values()
                        if v not in self.in_ports and v not in self.out_ports
                        and "[" not in v})
        for w in wires:
            L.append(f"  wire {w};")
        L.append("")
        for li, (_, cell, *_ ) in enumerate(self.insts):
            args = ", ".join(f".{pin}({self.net_name[net]})"
                             for pin, net in sorted(self.conns[li].items()))
            L.append(f"  {cell} {self.inst_name[li]} ({args});")
        L.append("endmodule")
        return "\n".join(L)
