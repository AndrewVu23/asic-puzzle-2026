"""
Structural analysis of an extracted netlist.
"""
from __future__ import annotations
import collections, math
from tools.netlist import Netlist, base_cell, OUTPUT_PINS
from tools import cells


class Analysis:
    def __init__(self, nl: Netlist):
        self.nl = nl
        self.base = [base_cell(c) for _, c, *_ in nl.insts]
        self.drv = {}
        for li in range(len(nl.insts)):
            for pin, net in nl.conns[li].items():
                if pin in OUTPUT_PINS:
                    self.drv[net] = li
        self.fanin = []
        for li in range(len(nl.insts)):
            s = set()
            for pin, net in nl.conns[li].items():
                if pin not in OUTPUT_PINS:
                    d = self.drv.get(net)
                    if d is not None:
                        s.add(d)
            self.fanin.append(s)
        self.fanout = collections.defaultdict(set)
        for li, srcs in enumerate(self.fanin):
            for s in srcs:
                self.fanout[s].add(li)
        self.is_flop = [b in cells.SEQUENTIAL for b in self.base]
        self.flops = [i for i, f in enumerate(self.is_flop) if f]

    # cones
    def cone(self, net, stop_at_flops=True):
        # Transitive fan-in of a net; optionally stop at flop outputs
        seed = self.drv.get(net)
        if seed is None:
            return set(), set()
        seen, stack, flops = set(), [seed], set()
        while stack:
            u = stack.pop()
            if u in seen:
                continue
            seen.add(u)
            if self.is_flop[u]:
                flops.add(u)
                if stop_at_flops:
                    continue
            stack.extend(self.fanin[u] - seen)
        return seen, flops

    def full_cone(self, net):
        seen, _ = self.cone(net, stop_at_flops=False)
        return seen

    # flop graph
    def flop_edges(self):
        # flop -> set(flops feeding its D through pure combinational logic)
        edges = {}
        for f in self.flops:
            spec = cells.SEQUENTIAL[self.base[f]]
            dnet = self.nl.conns[f].get(spec["d"])
            src = set()
            if dnet is not None:
                seed = self.drv.get(dnet)
                if seed is not None:
                    seen, stack = set(), [seed]
                    while stack:
                        u = stack.pop()
                        if u in seen:
                            continue
                        seen.add(u)
                        if self.is_flop[u]:
                            src.add(u); continue
                        stack.extend(self.fanin[u] - seen)
            edges[f] = src
        return edges

    def chains(self):
        # Maximal simple chains a->b where b's D depends only on a
        e = self.flop_edges()
        indeg = collections.Counter()
        simple = {}
        for f, src in e.items():
            if len(src) == 1:
                s = next(iter(src))
                simple[f] = s
                indeg[s] += 1
        starts = [f for f in simple if simple[f] not in simple or indeg[simple[f]] > 1]
        chains, used = [], set()
        for f in self.flops:
            if f in used:
                continue
            # walk backwards to a chain head
            head, guard = f, 0
            while head in simple and indeg[simple[head]] == 1 and guard < 500:
                nxt = simple[head]
                if nxt in used or nxt == f:
                    break
                head = nxt; guard += 1
            # walk forwards
            ch, cur = [head], head
            used.add(head)
            fwd = {v: k for k, v in simple.items() if indeg[v] == 1}
            while cur in fwd and fwd[cur] not in used:
                cur = fwd[cur]; ch.append(cur); used.add(cur)
            if len(ch) > 1:
                chains.append(ch)
        return chains

    # physical
    def clusters(self, grid=20000):
        buckets = collections.defaultdict(list)
        for li, (_, cell, x, y, *_ ) in enumerate(self.nl.insts):
            buckets[(x // grid, y // grid)].append(li)
        return buckets

    def bbox(self, idxs):
        xs = [self.nl.insts[i][2] for i in idxs]
        ys = [self.nl.insts[i][3] for i in idxs]
        return min(xs), min(ys), max(xs), max(ys)
