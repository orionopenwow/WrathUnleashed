#!/usr/bin/env python3
"""Leyline mesh scale simulation (docs/LEYLINE-MESH.md, "Scale evidence"). In-process, no network.

    python3 hosting/mesh-sim/meshsim.py [--quick] [--seed 7] [--json out.json]

Five parts:
  A. gossip (numpy model of wurelay/meshnode.py's policy: push what is new to F peers, pull one peer every K rounds)
     at 1k / 10k / 100k nodes: rounds to reach 99.9 % and 100 % of the live honest nodes, messages per node;
     with 30 % of nodes offline (stale views), and with 10 % / 30 % malicious nodes that drop everything and push
     forgeries;
  B. the real merge code (wunet.mesh.Store with real Ed25519 signatures) on a sampled network of a few hundred
     nodes: forged, tampered, replayed-after-expiry and equivocating records, 30 % churn; counts what honest nodes
     accepted;
  C. a Kademlia-style DHT (k=8, alpha=3, 62-bit ids, lazily built routing tables) at 1k / 10k / 100k nodes: hops and
     queries per lookup, success with 30 % churn and with 10 % nodes answering with junk;
  D. relay choice for 100 000 players with the real wunet.mesh.choose_endpoint: seeds plus community relays, stale
     load, a "seeds gone" run, and how many community relays 100 000 players need;
  E. bandwidth arithmetic from real record sizes.

What it does not prove: real networks (NAT, packet loss, TCP/TLS costs, asymmetric links), adaptive attackers
(Sybil floods of the peer view, targeted eclipse), CPU limits of small nodes, or that enough people volunteer.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "kit", "tools"))
from wunet import keys, mesh  # noqa: E402

ROUND_S = 10            # RELAY_MESH_EVERY


# ------------------------------------------------------------------------------------------------ A. gossip model
def gossip(n, rng, fanout=3, view=24, pull_every=6, offline=0.0, malicious=0.0, max_rounds=200, sources=1):
    """One new record, published by `sources` random honest live nodes, spreading. Returns stats."""
    views = rng.integers(0, n, size=(n, view), dtype=np.int64)
    alive = rng.random(n) >= offline
    bad = (rng.random(n) < malicious) & alive
    honest = alive & ~bad
    have = np.zeros(n, bool)
    fresh = np.zeros(n, bool)
    start = rng.choice(np.flatnonzero(honest), size=sources, replace=False)
    have[start] = fresh[start] = True
    msgs = np.zeros(n, np.int64)
    forged_recv = np.zeros(n, np.int64)
    target = honest.sum()
    r999 = r100 = None
    for r in range(1, max_rounds + 1):
        nxt = np.zeros(n, bool)
        # push: honest nodes push what is new to `fanout` peers from their view
        senders = np.flatnonzero(fresh & honest)
        if senders.size:
            cols = rng.integers(0, view, size=(senders.size, fanout))
            tg = views[senders[:, None], cols].ravel()
            msgs[senders] += fanout
            ok = alive[tg] & ~bad[tg] & ~have[tg]
            got = np.unique(tg[ok])
            have[got] = True
            nxt[got] = True
        # pull: every node asks one peer every `pull_every` rounds (every round when it has nothing new)
        pullers = np.flatnonzero(honest & ((r % pull_every == 1) | ~fresh))
        if pullers.size:
            peer = views[pullers, rng.integers(0, view, size=pullers.size)]
            msgs[pullers] += 1
            ok = alive[peer] & ~bad[peer] & have[peer] & ~have[pullers]
            got = pullers[ok]
            have[got] = True
            nxt[got] = True
        # forgers push junk to fanout peers every round (honest nodes verify and drop it)
        bads = np.flatnonzero(bad)
        if bads.size:
            tg = views[bads[:, None], rng.integers(0, view, size=(bads.size, fanout))].ravel()
            np.add.at(forged_recv, tg, 1)
        fresh = nxt
        frac = (have & honest).sum() / target
        if r999 is None and frac >= 0.999:
            r999 = r
        if frac >= 1.0:
            r100 = r
            break
    hm = msgs[honest]
    return {"nodes": n, "offline": offline, "malicious": malicious, "rounds_99_9": r999, "rounds_100": r100,
            "seconds_99_9": None if r999 is None else r999 * ROUND_S,
            "reached": round(float((have & honest).sum() / target), 5),
            "msgs_per_node_mean": round(float(hm.mean()), 2), "msgs_per_node_max": int(hm.max()),
            "forged_per_honest_node_per_round": round(float(forged_recv[honest].mean() / max(1, r)), 2)}


# ------------------------------------------------------------------------------------------------ B. real merge code
class SimNode:
    def __init__(self, i):
        self.i, self.store, self.fresh, self.up = i, mesh.Store(), [], True

    def receive(self, recs, now):
        for r in recs:
            ok, _ = self.store.offer(r, now)
            if ok:
                self.fresh.append(self.store.recs[self.store.last_id])


def real_merge(rng, n=300, realms=12, churn=0.3, malicious=0.1, rounds=25, fanout=3):
    now = 1_800_000_000
    pyr = random.Random(int(rng.integers(1 << 30)))
    nodes = [SimNode(i) for i in range(n)]
    bad = set(pyr.sample(range(n), int(n * malicious)))
    views = {i: pyr.sample(range(n), 16) for i in range(n)}
    relay_sec = keys.new_secret()
    honest_realms, forged = {}, []
    t0 = time.time()
    for k in range(realms):
        sec = keys.new_secret()
        pub = keys.public_key(sec)
        rid = keys.realm_id(pub)
        b = {"v": 1, "realm_id": rid, "pubkey": pub.hex(), "seq": 1, "ts": now, "relay": "relay.sim",
             "record": {"name": f"Realm {k}"}, "status": {"online": True, "players": k}}
        rec = mesh.realm_record(b, keys.sign_doc(sec, b, keys.CTX_HEARTBEAT),
                                [mesh.endpoint(relay_sec, rid, "relay.sim", 40000 + 2 * k, 40001 + 2 * k, True, now)])
        honest_realms["r-" + rid] = rec
        t = json.loads(json.dumps(rec))
        t["beat"]["status"]["players"] = 9999                    # tampered
        forged.append(t)
        b2 = dict(b, seq=2, record={"name": "Hijacked"})          # someone else's key, same realm id
        forged.append(mesh.realm_record(b2, keys.sign_doc(keys.new_secret(), b2, keys.CTX_HEARTBEAT)))
        e = mesh.endpoint(keys.new_secret(), rid, "evil.sim", 1, 2, True, now)  # endpoint on a relay never chosen
        forged.append(mesh.realm_record(b, rec["sig"], [e]))
    dead = mesh.realm_record(*_dead_realm(now - mesh.REALM_TTL - 60))   # a realm that stopped beating
    forged.append(dead)
    honest_ids = [i for i in range(n) if i not in bad]
    for k, (rid, rec) in enumerate(honest_realms.items()):
        nodes[honest_ids[k % len(honest_ids)]].receive([rec], now)
    msgs = 0
    for r in range(rounds):
        for nd in nodes:          # churn: 30 % of nodes offline each round, chosen afresh
            nd.up = pyr.random() >= churn
        for nd in nodes:
            if not nd.up:
                continue
            peers = [nodes[j] for j in pyr.sample(views[nd.i], fanout)]
            if nd.i in bad:
                for p in peers:
                    if p.up:
                        p.receive(forged, now)
                        msgs += 1
                continue
            fresh, nd.fresh = nd.fresh, []
            for p in peers:
                if p.up and fresh:
                    p.receive(fresh, now)
                    msgs += 1
            if r % 6 == 0 or not fresh:
                p = nodes[pyr.choice(views[nd.i])]
                if p.up and p.i not in bad:
                    nd.receive(list(p.store.recs.values()), now)
                    msgs += 1
    honest_nodes = [nodes[i] for i in honest_ids]
    complete = sum(1 for nd in honest_nodes if all(rid in nd.store.recs for rid in honest_realms))
    accepted_forged = sum(1 for nd in honest_nodes for rid, rec in nd.store.recs.items()
                          if rec["kind"] == "realm" and (rec["beat"]["record"]["name"] in ("Hijacked",)
                                                         or rec["beat"]["status"].get("players") == 9999
                                                         or any(e["att"]["relay"] == "evil.sim" for e in rec["endpoints"])
                                                         or rid not in honest_realms))
    # expiry: 16 minutes later every honest record has gone everywhere unless re-published
    later = now + mesh.REALM_TTL + 1
    for nd in honest_nodes:
        nd.store.sweep(later)
    left = sum(len(nd.store.realms()) for nd in honest_nodes)
    return {"nodes": n, "realms": realms, "churn": churn, "malicious": malicious, "rounds": rounds,
            "honest_nodes_with_every_realm": f"{complete}/{len(honest_nodes)}",
            "forged_or_tampered_records_accepted": accepted_forged,
            "refused_offers": sum(nd.store.stats["refused"] for nd in honest_nodes),
            "records_left_after_expiry": left, "messages": msgs, "seconds": round(time.time() - t0, 1)}


def _dead_realm(ts):
    sec = keys.new_secret()
    pub = keys.public_key(sec)
    b = {"v": 1, "realm_id": keys.realm_id(pub), "pubkey": pub.hex(), "seq": 1, "ts": ts, "relay": "relay.sim",
         "record": {"name": "Gone"}, "status": {"online": True}}
    return b, keys.sign_doc(sec, b, keys.CTX_HEARTBEAT)


# ------------------------------------------------------------------------------------------------ C. DHT
class DHT:
    BITS = 62

    def __init__(self, n, rng, k=8):
        self.n, self.k, self.rng = n, k, rng
        self.ids = np.unique(rng.integers(0, 1 << self.BITS, size=n, dtype=np.int64))
        self.n = len(self.ids)
        self.tables = {}

    def table(self, i):
        t = self.tables.get(i)
        if t is not None:
            return t
        x = int(self.ids[i])
        g = np.random.default_rng(i * 2654435761 % (1 << 32))
        buckets = []
        for b in range(self.BITS):
            shift = self.BITS - 1 - b
            lo = ((x >> shift) ^ 1) << shift
            hi = lo + (1 << shift)
            a, z = np.searchsorted(self.ids, lo), np.searchsorted(self.ids, hi)
            if z - a <= 0:
                buckets.append(np.empty(0, np.int64))
                continue
            take = min(self.k, z - a)
            buckets.append(a + g.choice(z - a, size=take, replace=False))
        self.tables[i] = buckets
        return buckets

    def closest_known(self, i, target, want):
        x = int(self.ids[i])
        d = x ^ target
        b0 = self.BITS - d.bit_length() if d else self.BITS - 1
        out = []
        t = self.table(i)
        for b in list(range(b0, self.BITS)) + list(range(b0 - 1, -1, -1)):
            if b < len(t):
                out.extend(int(c) for c in t[b])
            if len(out) >= want * 2:
                break
        out.sort(key=lambda c: int(self.ids[c]) ^ target)
        return out[:want]

    def lookup(self, start, target, alive, liar, alpha=3):
        """Iterative lookup. Returns (hops, queries, closest live node found == the true one, replica found)."""
        k = self.k
        short = self.closest_known(start, target, k)
        queried, hops, queries = {start}, 0, 0
        seen = set(short)
        while True:
            cand = [c for c in short if c not in queried][:alpha]
            if not cand:
                break
            hops += 1
            for c in cand:
                queried.add(c)
                queries += 1
                if not alive[c]:
                    short.remove(c)
                    continue
                if liar[c]:
                    got = [int(x) for x in self.rng.integers(0, self.n, size=k)]      # junk contacts
                else:
                    got = self.closest_known(c, target, k)
                for g in got:
                    if g not in seen:
                        seen.add(g)
                        short.append(g)
            short = sorted(set(short), key=lambda c: int(self.ids[c]) ^ target)[:k]
            if hops > 40:
                break
        live_ids = np.flatnonzero(alive & ~liar)
        true = int(live_ids[np.argmin(np.bitwise_xor(self.ids[live_ids], target))])
        return hops, queries, (true in short) or (true in queried)


def dht(n, rng, lookups=300, offline=0.0, liars=0.0):
    d = DHT(n, rng)
    alive = rng.random(d.n) >= offline
    liar = (rng.random(d.n) < liars) & alive
    good = np.flatnonzero(alive & ~liar)
    hops, qs, ok = [], [], 0
    for _ in range(lookups):
        s = int(rng.choice(good))
        t = int(rng.integers(0, 1 << DHT.BITS, dtype=np.int64))
        h, q, found = d.lookup(s, t, alive, liar)
        hops.append(h)
        qs.append(q)
        ok += found
    return {"nodes": d.n, "offline": offline, "liars": liars, "hops_mean": round(float(np.mean(hops)), 2),
            "hops_p95": int(np.percentile(hops, 95)), "queries_mean": round(float(np.mean(qs)), 1),
            "found_closest_live_node": round(ok / lookups, 3)}


# ------------------------------------------------------------------------------------------------ D. relay choice
REGIONS = ["na-east", "na-west", "sa", "eu", "africa", "me", "asia", "oce"]
NEAR = {("na-east", "na-west"), ("na-east", "sa"), ("na-east", "eu"), ("eu", "africa"), ("eu", "me"), ("me", "asia"),
        ("asia", "oce"), ("na-west", "asia")}


def rtt(a, b, rng):
    if a == b:
        return float(rng.uniform(15, 40))
    if (a, b) in NEAR or (b, a) in NEAR:
        return float(rng.uniform(70, 120))
    return float(rng.uniform(150, 300))


def relay_choice(rng, players=100_000, realms=2000, volunteers=300, seeds=("na-east", "eu", "asia"), vol_streams=512,
                 seed_streams=8192, refresh=2000, seeds_gone=False, scale_out=False):
    """`scale_out`: when every endpoint of a realm is full, its agent attaches one more community relay with room
    (nearest region first). That is designed (docs/LEYLINE-MESH.md, "multi-relay agents"), not built."""
    pyr = random.Random(int(rng.integers(1 << 30)))
    relays = {}
    for i, rg in enumerate(seeds):
        if not seeds_gone:
            relays[f"seed{i}.sim"] = {"region": rg, "caps": {"streams": seed_streams, "realms": 2000}, "load": {"streams": 0, "realms": 0}, "seed": True}
    for i in range(volunteers):
        relays[f"v{i}.sim"] = {"region": pyr.choice(REGIONS), "caps": {"streams": vol_streams, "realms": 25},
                               "load": {"streams": 0, "realms": 0}, "seed": False}
    seed_hosts = {h for h, r in relays.items() if r["seed"]}
    by_region = {rg: [h for h, r in relays.items() if r["region"] == rg and not r["seed"]] for rg in REGIONS}
    now = 1_800_000_000
    recs = []
    for k in range(realms):
        rg = pyr.choice(REGIONS)
        chosen = []
        if seed_hosts:
            chosen.append(min(seed_hosts, key=lambda h: rtt(rg, relays[h]["region"], rng)))
        # the host's agent adds up to 2 community relays in its region that still have room for realms
        room = [h for h in by_region[rg] if relays[h]["load"]["realms"] < relays[h]["caps"]["realms"]]
        for h in pyr.sample(room, min(2, len(room))):
            chosen.append(h)
            relays[h]["load"]["realms"] += 1
        if not chosen:
            others = [h for h in relays if relays[h]["load"]["realms"] < relays[h]["caps"]["realms"]]
            if others:
                chosen.append(pyr.choice(others))
                relays[chosen[-1]]["load"]["realms"] += 1
        eps = [{"att": {"relay": h, "ws": True, "node": h, "ts": now}} for h in chosen]
        recs.append(({"beat": {"relay": chosen[0] if chosen else None}, "endpoints": eps}, rg))
    # popularity: Zipf-ish over realms
    w = 1.0 / np.arange(1, realms + 1) ** 0.9
    w /= w.sum()
    picks = rng.choice(realms, size=players, p=w)
    published = {h: json.loads(json.dumps(r)) for h, r in relays.items()}   # what the mesh last said (stale)
    streams = {h: 0 for h in relays}
    lat, base_lat, unserved, over, scaled = [], [], 0, 0, 0
    for p, ri in enumerate(picks):
        if p % refresh == 0:
            for h in relays:
                published[h]["load"]["streams"] = streams[h]
        rec, rrg = recs[ri]
        prg = rrg if pyr.random() < 0.7 else pyr.choice(REGIONS)          # most players are near the realm's host
        m = {h: rtt(prg, relays[h]["region"], rng) for h in {e["att"]["relay"] for e in rec["endpoints"]}}
        ep = mesh.choose_endpoint(rec, published, m, volunteers=True, seeds=seed_hosts)
        if ep is None:
            unserved += 1
            continue
        h = ep["att"]["relay"]
        if streams[h] + 2 > relays[h]["caps"]["streams"]:
            # the relay refuses (it enforces its caps); the launcher tries the next endpoint
            alt = [e for e in rec["endpoints"] if streams[e["att"]["relay"]] + 2 <= relays[e["att"]["relay"]]["caps"]["streams"]]
            if not alt and scale_out:
                room = [x for x in relays if not relays[x]["seed"] and streams[x] + 2 <= relays[x]["caps"]["streams"]
                        and relays[x]["load"]["realms"] < relays[x]["caps"]["realms"]
                        and x not in {e["att"]["relay"] for e in rec["endpoints"]}]
                if room:
                    x = min(room, key=lambda x: (rtt(rrg, relays[x]["region"], rng) > 50, streams[x]))
                    relays[x]["load"]["realms"] += 1
                    rec["endpoints"].append({"att": {"relay": x, "ws": True, "node": x, "ts": now}})
                    m[x] = rtt(prg, relays[x]["region"], rng)
                    alt = [rec["endpoints"][-1]]
                    scaled += 1
            if not alt:
                unserved += 1
                continue
            over += 1
            h = min(alt, key=lambda e: m[e["att"]["relay"]])["att"]["relay"]
        streams[h] += 2
        lat.append(m[h])
        if seed_hosts:
            base_lat.append(min(rtt(prg, relays[s]["region"], rng) for s in seed_hosts))
    util = [streams[h] / relays[h]["caps"]["streams"] for h in relays]
    on_seeds = sum(streams[h] for h in seed_hosts) / max(1, sum(streams.values()))
    return {"players": players, "realms": realms, "volunteers": volunteers, "seeds": 0 if seeds_gone else len(seeds),
            "scale_out": scale_out, "served": players - unserved, "unserved": unserved,
            "first_choice_full_retried": over, "relays_added_by_scale_out": scaled,
            "share_through_seeds": round(on_seeds, 3),
            "rtt_ms_median": round(float(np.median(lat)), 1) if lat else None,
            "rtt_ms_median_seeds_only": round(float(np.median(base_lat)), 1) if base_lat else None,
            "relay_util_max": round(max(util), 3), "relays_over_90pct": sum(u > 0.9 for u in util)}


# ------------------------------------------------------------------------------------------------ E. bandwidth
def bandwidth():
    now = 1_800_000_000
    sec = keys.new_secret()
    pub = keys.public_key(sec)
    rid = keys.realm_id(pub)
    b = {"v": 1, "realm_id": rid, "pubkey": pub.hex(), "seq": 1761700000123, "ts": now, "relay": "relay.openvanilla.app",
         "record": {"name": "A Typical Realm Name", "tagline": "x" * 60, "summary": "y" * 250, "type": "PvP",
                    "ruleset": "custom", "rules": ["Be kind to each other", "No cheating"], "tags": ["pvp", "bots"],
                    "region": "eu", "language": "en", "max_players": 100, "build": 12340, "core": "azerothcore"},
         "status": {"online": True, "players": 40, "bots": 100, "uptime_s": 86400}}
    rec = mesh.realm_record(b, keys.sign_doc(sec, b, keys.CTX_HEARTBEAT),
                            [mesh.endpoint(keys.new_secret(), rid, "relay.openvanilla.app", 40000, 40001, True, now)])
    size = mesh.size(rec)
    import gzip
    many = []
    for k in range(50):                      # 50 different realms (own keys, own text): what a snapshot holds
        s2 = keys.new_secret()
        p2 = keys.public_key(s2)
        b2 = json.loads(json.dumps(b))
        b2.update(realm_id=keys.realm_id(p2), pubkey=p2.hex(), seq=b["seq"] + k)
        b2["record"].update(name=f"Realm number {k}", tagline=os.urandom(30).hex(), summary=os.urandom(120).hex())
        many.append(mesh.realm_record(b2, keys.sign_doc(s2, b2, keys.CTX_HEARTBEAT),
                                      [mesh.endpoint(keys.new_secret(), b2["realm_id"], "relay.openvanilla.app", 40000, 40001, True, now)]))
    sizes = {"realm_record_bytes": size,
             "realm_record_gzip_bytes_in_a_snapshot": round(len(gzip.compress(json.dumps(many).encode())) / 50)}
    out = {"record": sizes, "per_node": []}
    for realms in (1000, 2000, 10_000):
        per_s = realms / mesh.REFRESH                                  # records a second, network wide
        push = per_s * size * 3                                        # each node pushes each record to 3 peers
        recv = per_s * size * 3                                        # and receives about as many copies
        out["per_node"].append({"realms": realms, "records_per_s": round(per_s, 1),
                                "node_kbytes_per_s_up": round(push / 1024, 1), "node_kbytes_per_s_down": round(recv / 1024, 1),
                                "snapshot_mbytes_gzip": round(realms * sizes["realm_record_gzip_bytes_in_a_snapshot"] / 1e6, 2)})
    # 100 000 launchers, the Realms page open on 10 % of them, a refresh every 2 minutes, spread over the nodes
    for nodes in (5, 50, 300):
        snap = 2000 * sizes["realm_record_gzip_bytes_in_a_snapshot"]
        rate = 100_000 * 0.10 / 120
        out.setdefault("light_clients", []).append({"mesh_nodes": nodes, "realms": 2000, "snapshots_per_s_total": round(rate, 1),
                                                    "node_mbit_per_s": round(rate * snap * 8 / nodes / 1e6, 2)})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="1k and 10k only, fewer lookups")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    rng = np.random.default_rng(a.seed)
    sizes = (1000, 10_000) if a.quick else (1000, 10_000, 100_000)
    res = {"seed": a.seed, "gossip": [], "dht": [], "relay_choice": []}
    t0 = time.time()
    for n in sizes:
        for off, mal in ((0.0, 0.0), (0.3, 0.0), (0.0, 0.1), (0.3, 0.3)):
            r = gossip(n, rng, offline=off, malicious=mal)
            res["gossip"].append(r)
            print("gossip", json.dumps(r), flush=True)
    r = real_merge(rng, n=120 if a.quick else 300)
    res["real_merge"] = r
    print("real_merge", json.dumps(r), flush=True)
    for n in sizes:
        for off, liars in ((0.0, 0.0), (0.3, 0.0), (0.0, 0.1), (0.3, 0.1)):
            r = dht(n, rng, lookups=100 if a.quick else 300, offline=off, liars=liars)
            res["dht"].append(r)
            print("dht", json.dumps(r), flush=True)
    for kw in ({}, {"scale_out": True}, {"seeds_gone": True, "volunteers": 400}, {"seeds_gone": True, "volunteers": 400, "scale_out": True},
               {"seeds_gone": True, "volunteers": 250, "scale_out": True}, {"seeds_gone": True, "volunteers": 150, "scale_out": True}):
        r = relay_choice(rng, players=20_000 if a.quick else 100_000, **kw)
        res["relay_choice"].append(r)
        print("relay_choice", json.dumps(r), flush=True)
    res["bandwidth"] = bandwidth()
    print("bandwidth", json.dumps(res["bandwidth"]), flush=True)
    res["seconds"] = round(time.time() - t0, 1)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(res, f, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
