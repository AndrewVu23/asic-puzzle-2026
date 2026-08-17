"""sky130_fd_sc_hd cell function library.

Functions are derived from the *official* behavioural models in vendor/sky130
by parsing their structural primitive netlists -- not guessed from cell names.
Sequential cells use UDP primitives, so those are modelled explicitly.
"""
from __future__ import annotations
import os, re, glob, functools

MODELDIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "vendor", "sky130")

PRIM = {"and", "or", "nand", "nor", "xor", "xnor", "not", "buf",
        "pullup", "pulldown"}
SUPPLY = {"VPWR", "VGND", "VPB", "VNB"}
NOISE = {"notifier", "awake", "cond0", "cond1", "cond2", "cond3", "cond4"}

# cells with no logic function at all
PHYSICAL = {"decap", "tapvpwrvgnd", "diode", "fill", "tap"}
# sequential cells, modelled by hand (their models are UDP-based)
SEQUENTIAL = {
    "dfxtp": dict(clk="CLK", d="D"),
    "dfrtp": dict(clk="CLK", d="D", rst="RESET_B", rst_val=0),
    "dfstp": dict(clk="CLK", d="D", rst="SET_B", rst_val=1),
}

_gate_re = re.compile(r"^\s*([A-Za-z_][\w$]*)\s+(\w+)\s*\(([^;]*)\)\s*;", re.M)
_port_re = re.compile(r"^\s*(input|output)\s+(?:wire\s+|reg\s+)?(\w+)\s*;", re.M)


def _clean(sig):
    sig = sig.strip()
    return sig[:-8] if sig.endswith("_delayed") else sig


@functools.lru_cache(maxsize=None)
def load(base):
    """-> dict(name, inputs, outputs, gates) for a base cell name."""
    path = os.path.join(MODELDIR, base + ".v")
    txt = open(path, errors="replace").read()
    m = re.search(r"`celldefine(.*?)endmodule", txt, re.S)
    body = m.group(1) if m else txt
    ins, outs = [], []
    for d, nm in _port_re.findall(body):
        (ins if d == "input" else outs).append(nm)
    ins = [p for p in ins if p not in SUPPLY]
    gates = []
    for prim, _inst, args in _gate_re.findall(body):
        if prim not in PRIM:
            if prim.startswith("sky130_fd_sc_hd__udp"):
                gates.append(("__udp__", prim, [_clean(a) for a in args.split(",")]))
            continue
        a = [_clean(x) for x in args.split(",") if x.strip()]
        if not a:
            continue
        gates.append((prim, a[0], a[1:]))
    return dict(name=base, inputs=ins, outputs=outs, gates=gates)


def _eval_gate(prim, vals):
    if prim == "and":   return all(vals)
    if prim == "or":    return any(vals)
    if prim == "nand":  return not all(vals)
    if prim == "nor":   return not any(vals)
    if prim == "xor":   return functools.reduce(lambda a, b: a ^ b, vals, False)
    if prim == "xnor":  return not functools.reduce(lambda a, b: a ^ b, vals, False)
    if prim == "not":   return not vals[0]
    if prim == "buf":   return vals[0]
    raise ValueError(prim)


@functools.lru_cache(maxsize=None)
def combinational(base):
    """-> f(dict of input pin -> bool) -> dict of output pin -> bool"""
    if base in PHYSICAL:
        return None
    if base == "conb":
        return lambda v: {"HI": True, "LO": False}
    if base in SEQUENTIAL:
        return None
    spec = load(base)
    gates, outs = spec["gates"], spec["outputs"]

    def f(v, gates=gates, outs=outs):
        env = dict(v)
        env["VPWR"] = env["VPB"] = True
        env["VGND"] = env["VNB"] = False
        pending = list(gates)
        for _ in range(len(pending) + 2):
            again = []
            for g in pending:
                if g[0] == "__udp__":
                    prim, _p, args = g
                    o = args[0]
                    if "mux_2to1" in _p:          # (out, A0, A1, S)
                        a0, a1, s = args[1], args[2], args[3]
                        if all(k in env for k in (a0, a1, s)):
                            env[o] = env[a1] if env[s] else env[a0]
                        else:
                            again.append(g)
                    continue
                prim, o, srcs = g
                if prim in ("pullup", "pulldown"):
                    env[o] = (prim == "pullup"); continue
                if all(s in env for s in srcs):
                    env[o] = _eval_gate(prim, [env[s] for s in srcs])
                else:
                    again.append(g)
            pending = again
            if not pending:
                break
        return {o: bool(env.get(o, False)) for o in outs}
    return f


def pin_dirs(base):
    spec = load(base)
    return set(spec["inputs"]), set(spec["outputs"])


def all_bases():
    return sorted(os.path.basename(p)[:-2] for p in glob.glob(os.path.join(MODELDIR, "*.v")))


# --- self-check against the equations stated in the model headers ----------
_eq_re = re.compile(r"^\s*\*\s+([A-Z][A-Z0-9_]*)\s*=\s*(.+?)\s*$", re.M)


def header_equations(base):
    txt = open(os.path.join(MODELDIR, base + ".v"), errors="replace").read()
    head = txt.split("`celldefine")[0]
    out = {}
    for o, e in _eq_re.findall(head):
        if e.endswith((".", "model.", ":")) or "=" in e.replace("==", ""):
            continue
        if e.count("(") != e.count(")"):
            # upstream comment typo (e.g. nor3b); the structural body is
            # authoritative, so just don't use this line as an oracle.
            continue
        out[o] = e
    return out


def _py(expr):
    return ("(" + expr.replace("!", " not ").replace("&", " and ")
                      .replace("|", " or ").replace("^", " != ") + ")")


def selftest(verbose=False):
    """Evaluate every combinational cell against its header equation."""
    import itertools
    bad, checked = [], 0
    for base in all_bases():
        if base in PHYSICAL or base in SEQUENTIAL or base == "conb":
            continue
        eqs = header_equations(base)
        f = combinational(base)
        spec = load(base)
        ins = spec["inputs"]
        if not eqs or len(ins) > 12:
            continue
        for o, expr in eqs.items():
            if o not in spec["outputs"]:
                continue
            code = compile(_py(expr), "<eq>", "eval")
            for combo in itertools.product([False, True], repeat=len(ins)):
                v = dict(zip(ins, combo))
                try:
                    want = bool(eval(code, {}, dict(v)))
                except Exception as ex:
                    bad.append((base, o, f"eval-error {ex}")); break
                got = f(v)[o]
                if got != want:
                    bad.append((base, o, v, got, want)); break
            checked += 1
    return checked, bad


if __name__ == "__main__":
    n, bad = selftest()
    print(f"cell models: {len(all_bases())}")
    print(f"outputs cross-checked against header equations: {n}")
    print(f"mismatches: {len(bad)}")
    for b in bad[:10]:
        print("   ", b)
