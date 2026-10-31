"""The shared rate limiter (stream/ratelimit.py): it forgets old keys by time, stays bounded, keeps global caps through
floods and clear(), buckets IPv6 by /64, and holds its counts across threads.

    python3 -I stream/tests/test_ratelimit.py stream/ratelimit.py
"""
import importlib.util, os, sys, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(HERE), "ratelimit.py")
spec = importlib.util.spec_from_file_location("wu_ratelimit_t", SRC)
R = importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)
fails = count = 0


def check(name, cond, extra=""):
    global fails, count
    count += 1
    print(("PASS " if cond else "FAIL ") + name + (f"  {extra}" if extra and not cond else ""))
    fails += 0 if cond else 1


class Clock:
    def __init__(self): self.t = 1000.0
    def __call__(self): return self.t


# ---------------------------------------------------------------- the window
c = Clock()
L = R.Limiter(60, clock=c)
check("first hits pass", all(L.hit("a", 3) for _ in range(3)))
check("the limit holds", not L.hit("a", 3))
c.t += 61
check("the window slides", L.hit("a", 3))
check("per-key window: 10 s key", L.hit("short", 1, seconds=10) and not L.hit("short", 1, seconds=10))
c.t += 11
check("per-key window slides on its own clock", L.hit("short", 1, seconds=10))

# ---------------------------------------------------------------- 25k old keys get swept
c = Clock()
L = R.Limiter(60, clock=c, max_keys=100000)
for i in range(25000):
    L.hit(f"ip{i}", 10)
check("25k keys held", len(L) == 25000, len(L))
c.t += 30
L.hit("fresh", 10)
check("no sweep before the window passes", len(L) == 25001, len(L))
c.t += 31
t0 = time.perf_counter()
L.hit("fresh2", 10)   # this hit triggers the periodic sweep
took = time.perf_counter() - t0
check("the periodic sweep drops every key older than its window", len(L) == 2, len(L))
check("the sweep is quick (25k keys)", took < 0.5, f"{took:.3f}s")
check("sweep() by hand", L.sweep() == 0 and len(L) == 2)
c.t += 3600
check("sweep() drops the rest", L.sweep() == 2 and len(L) == 0)

# the old limiter's bug: a key with only stale hits was kept forever
c = Clock()
L = R.Limiter(60, clock=c)
L.hit("stale", 5)
c.t += 120
L.hit("other", 5)
check("a key whose newest hit is old is forgotten", "stale" not in L.q)

# ---------------------------------------------------------------- bounded memory, global caps
c = Clock()
L = R.Limiter(3600, clock=c, max_keys=1000, global_keys=("all",))
ok = 0
for i in range(5000):
    if L.hit("all", 300):
        ok += 1
    L.hit(f"10.{i // 250}.{i % 250}.1", 5)
check("the global cap holds under 5000 addresses", ok == 300, ok)
check("memory bounded by max_keys", len(L) == 1000, len(L))
check("evictions counted", L.evicted == 4000, L.evicted)
L.clear()
check("clear() empties per-address keys", len(L) == 0)
check("clear() keeps the global cap", not L.hit("all", 300) and L.count("all") == 300)
check("cap() is a global cap too", L.cap("day", 1) and not L.cap("day", 1))
for i in range(3000):
    L.hit(f"x{i}", 1)
check("a flood can't evict a cap", not L.cap("day", 1))
check("LRU evicts the oldest, keeps the newest", "x2999" in L.q and "x0" not in L.q)

# ---------------------------------------------------------------- buckets
B = R.bucket
check("IPv4 /32", B("203.0.113.7") == "203.0.113.7")
check("IPv6 /64", B("2001:db8:1:2:aaaa::1") == "2001:db8:1:2::/64")
check("same /64, same bucket", B("2001:db8:1:2::1") == B("2001:db8:1:2:ffff:ffff:ffff:ffff"))
check("other /64, other bucket", B("2001:db8:1:3::1") != B("2001:db8:1:2::1"))
check("IPv4-mapped counts as IPv4", B("::ffff:198.51.100.4") == "198.51.100.4")
check("brackets and zone ids", B("[fe80::1%eth0]") == "fe80::/64")
check("not an address: trimmed", B("x" * 200) == "x" * 64 and B("") == "")

# ---------------------------------------------------------------- threads
L = R.Limiter(60, global_keys=("g",))
passed = []
lock = threading.Lock()


def worker(n):
    mine = 0
    for i in range(400):
        if L.hit("shared", 1000):
            mine += 1
        L.hit("g", 500)
        L.hit(f"t{n}-{i}", 2)
    with lock:
        passed.append(mine)


ts = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
[t.start() for t in ts]
[t.join() for t in ts]
check("threads: exactly the limit passes", sum(passed) == 1000, sum(passed))
check("threads: the global cap is exact", L.count("g") == 500, L.count("g"))

# ---------------------------------------------------------------- deploy
STREAM = os.path.dirname(HERE)
fl = open(os.path.join(STREAM, "fastloop.sh"), encoding="utf-8").read()
bat = open(os.path.join(STREAM, "Update sign-in and warm-up.bat"), encoding="utf-8", errors="replace").read()
check("deploy: fastloop.sh backs up, puts back and installs ratelimit.py", fl.count("ratelimit.py") >= 5
      and 'install -m 644 ratelimit.py "$WU/portal/ratelimit.py"' in fl)
check("deploy: the .bat sends ratelimit.py", 'set "LINKS=%LINKS% ratelimit.py"' in bat and "ls ratelimit.py" in bat)

print(f"\n{count - fails}/{count} passed")
sys.exit(1 if fails else 0)
