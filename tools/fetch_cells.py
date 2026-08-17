"""Download sky130_fd_sc_hd behavioural models for the cell types we need."""
import os, sys, urllib.request, concurrent.futures as cf
DEST = "vendor/sky130"
URL = ("https://raw.githubusercontent.com/google/skywater-pdk-libs-sky130_fd_sc_hd"
       "/main/cells/{c}/sky130_fd_sc_hd__{c}.behavioral.v")

def get(c):
    p = os.path.join(DEST, c + ".v")
    if os.path.exists(p) and "SPDX" in open(p, errors="replace").read():
        return (c, "cached")
    for attempt in range(4):
        try:
            with urllib.request.urlopen(URL.format(c=c), timeout=60) as r:
                data = r.read().decode()
            if "SPDX" in data:
                open(p, "w").write(data)
                return (c, "ok")
        except Exception as ex:
            last = ex
    return (c, "FAIL")

if __name__ == "__main__":
    os.makedirs(DEST, exist_ok=True)
    cells = [l.strip() for l in open(sys.argv[1]) if l.strip()]
    bad = []
    with cf.ThreadPoolExecutor(8) as ex:
        for c, st in ex.map(get, cells):
            if st == "FAIL":
                bad.append(c)
    print("missing:", len(bad), bad)
