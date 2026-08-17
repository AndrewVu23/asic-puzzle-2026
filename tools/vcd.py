"""Tiny VCD reader: returns the ordered value-change timeline."""
from __future__ import annotations
import re


def read(path):
    ids, widths = {}, {}
    times = []            # [(t, {name: value_str})]
    cur, t = {}, None
    in_defs = True
    with open(path) as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            if in_defs:
                m = re.match(r"\$var\s+\w+\s+(\d+)\s+(\S+)\s+(\S+)(?:\s+\[[^\]]*\])?\s+\$end", line)
                if m:
                    w, sym, nm = m.groups()
                    ids[sym] = nm; widths[nm] = int(w)
                    continue
                if line.startswith("$enddefinitions"):
                    in_defs = False
                continue
            if line.startswith("#"):
                if t is not None:
                    times.append((t, dict(cur)))
                t = int(line[1:]); cur = {}
                continue
            if line[0] in "01xzXZ" and len(line) >= 2:
                val, sym = line[0], line[1:]
                if sym in ids:
                    cur[ids[sym]] = val
            elif line[0] in "bB":
                parts = line.split()
                if len(parts) == 2 and parts[1] in ids:
                    cur[ids[parts[1]]] = parts[0][1:]
            elif line[0] in "rR":
                pass
    if t is not None:
        times.append((t, dict(cur)))
    return ids, widths, times


def timeline(path):
    """-> (names, [(time, {name: str_value_at_that_time})]) with values held."""
    ids, widths, times = read(path)
    held, out = {}, []
    for t, ch in times:
        held.update(ch)
        out.append((t, dict(held)))
    return sorted(set(ids.values())), widths, out
