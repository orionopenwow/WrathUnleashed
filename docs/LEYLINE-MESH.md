# The Leyline mesh: a realm list and relays that don't depend on us

**Status (2026-10-29):** the core is built and tested. Everything is **off** behind flags. Our servers stay up as
seed nodes; the network must keep working without them.

## The goal

The owner's direction (23:25 Phoenix, 2026-10-29): anyone can host a realm in one click and appear on a worldwide
realm list, and players hop between realms with their own game files. It should be possible to release Leyline
without us hosting a relay, while our servers stay up. The design target is about 100 000 people.

Read that as two jobs:

1. **The realm list must not need us.**
   * Every fact on the list is signed by the realm or relay it describes.
   * Any node can hold the facts and pass them on: our relays, community relays, and later hosts.
   * Every player's launcher checks every signature itself.
2. **The relaying must not need us.**
   * Any host or launcher can opt in to relay for others, within caps.
   * Players pick a relay by latency and load.
   * Our seed relay is the last fallback, not the only path.

The torrent rule still holds: **only open content travels P2P or by torrent.** That means our code, mod
packages that passed the checker, theme packs and the Host pack. Never game data, never a game client.

---

## 1. Who is in the network

```
                 seed relays (ours: relay.openvanilla.app, ...)          bootstrap list, pinned keys
                        |  gossip (push + pull)  |
          community relays (RELAY_VOLUNTEER=1)  ---  other mesh nodes         full nodes: hold every record
                        |                        |
     host agents dial ONE relay (wss, outbound)     launchers pull snapshots from 2 peers + the seeds
                                                    and verify every record themselves (light clients)
```

* **Full nodes (mesh nodes)** are relays: ours (the seeds) and community relays. Each runs the relay with
  `RELAY_MESH=1`. They hold every record and gossip.
  * At the scale we aim for, that is hundreds to a few thousand nodes.
  * The simulation runs the gossip with up to 100 000 nodes, to leave headroom.
* **Light clients** are players' launchers, up to 100 000 of them.
  * They never gossip and never accept connections.
  * They pull a snapshot from a few full nodes and verify it locally.
  * A light client trusts no node. A node can only leave records out, and pulling from several sources defeats
    that.
* **Host agents** are not mesh nodes. An agent keeps dialing one relay, exactly as today.
  * That relay wraps the agent's signed heartbeat into a mesh record, so **no agent change is needed**.

## 2. Bootstrap and peer discovery

Each node finds peers in this order:

1. its own **peers cache**:
   * relays: `mesh-peers.json` next to `RELAY_STATE`;
   * launchers: `<app data>/cache/mesh-peers.json`;
2. relay records it has already verified (any node with `"mesh": true` and an `http` base);
3. the **bootstrap list**:
   * relays: `RELAY_MESH_BOOTSTRAP`, by default `https://relay.openvanilla.app`;
   * launchers: `mesh::SEEDS`, hard-coded in the release.

A launcher asks two cached peers first (a different pair each minute), then the seeds. It stops after three
sources have answered.

* While the seeds are up, every refresh includes a seed. That is the eclipse defense: a set of poisoned peers can
  hide realms, but the seed still shows them.
* When the seeds are down, the cached peers carry the list.
* `TODO(owner)`: pin the seeds' node keys in `wunet/mesh.py SEED_KEYS`, and add more seed names to `SEEDS` as
  they come up.

## 3. The records (signed, expiring)

The format is in `hosting/kit/tools/wunet/mesh.py`; `launcher/src-tauri/src/p2p/mesh.rs` applies the same rules.
Every signature is Ed25519 over `context + "\n" + canonical JSON` (sorted keys, no spaces, UTF-8). The context
strings are versioned.

| Kind | Signed by | Holds | Expires |
|---|---|---|---|
| `realm` | the **realm key** (the agent's existing heartbeat, `wu-listing-heartbeat-v1`) | name, text, tags, build, core, status (players and bots apart), `relay` / `relays` (the relays the realm chose) | 15 min after the beat's `ts` |
| endpoint, inside a realm record | the **relay's node key** (`leyline-mesh-endpoint-v1`) | relay host, the realm's auth and world ports, `ws` (whether the browser bridge is served), `ts` | 15 min |
| `relay` | the **node key** (`leyline-mesh-node-v1`) | host, `http` base, region, `volunteer`, `ws`, `mesh`, caps (realms, streams, KB/s), load (realms, streams) | 30 min |
| `block` | a **pinned staff key** (`leyline-mesh-block-v1`) | target (`r-<realm id>` or `n-<node id>`), reason, `ts`, `expires` | at most 90 days |

Why no node can forge a realm or keep a dead one alive:

* **Identity:** `realm id = base32(sha256(pubkey))[:16]` is recomputed from the key, so a record can't claim
  someone else's id. The same holds for node ids.
* **Contents:** every field the list shows comes from the realm's own signed beat. A changed byte breaks the
  signature.
* **Where to connect:** an endpoint counts only when two things are true. The relay signed it, and the realm
  itself named that relay in its signed beat. A relay can't attach itself to a realm that never chose it.
* **Liveness:** a realm record expires 15 minutes after the beat it carries. A dead realm stops beating, so its
  last record expires on every node at the same moment. Re-offering it is refused, so nobody can keep it on the
  list.
* **Merge rules** (`Store.offer`, `Merged::offer`):
  * the higher `seq` wins;
  * at an equal `seq` with identical bytes, the endpoints merge;
  * at an equal `seq` with different bytes (the key holder equivocating), the record with the smaller
    sha256(signature) wins, so every node keeps the same one;
  * a blocked target is refused and dropped.
* **Freshness:** the seed relay re-publishes an unchanged realm every 5 minutes (TTL / 3), and at once when the
  list text, online status, player count (in steps of 5) or signed relays change. Agents still beat every 60 s
  to their relay. The mesh carries at most one record per realm per 5 minutes.

## 4. The distributed realm list: gossip, with a DHT for later

Every node and every player wants the **whole** list (it is a browser), so the list is **replicated**, not
partitioned. Each full node holds every record. The gossip, in `hosting/relay/wurelay/meshnode.py`:

* **Push:** every `RELAY_MESH_EVERY` (10 s), a node sends what is new since the last round to `RELAY_MESH_FANOUT`
  (3) random peers. That goes to `POST /api/mesh/push`, in batches of up to 14 KB.
  * There is a cap of 120 records a minute per address.
  * A pusher is remembered as a peer only when a signed relay record vouches for its `http` base.
* **Pull** (anti-entropy):
  * Every 6th round, or every round when nothing is new, a node asks one peer for what changed since its cursor:
    `GET /api/mesh/records?since=<cursor>&epoch=<peer's epoch>`. A restarted peer has a new epoch, so the cursor
    resets.
  * `GET /api/mesh/summary` returns 256 bucket hashes. With them, two nodes can find the buckets they disagree on
    and fetch only those (`?buckets=0a,ff`).
* **Serving:**
  * `GET /api/mesh/snapshot`: every record, for launchers.
  * `GET /api/mesh/realms.json`: today's realms.json shape, built only from verified records.
  * `GET /api/mesh/node`, `GET /api/mesh/peers`.
* **Backward compatible:** `/api/listing/realms.json`, the heartbeat endpoint and claims are untouched. Today's
  relay simply also becomes one node of the mesh.

**DHT (designed, simulated, not built).** A Kademlia-style DHT is for two things the replicated list doesn't
cover:

* finding a single record by id without the whole list: an invite link, or a realm too new to have spread;
* peer discovery once there are more than about 10 000 full nodes.

The simulation (part C) shows lookups take 4 to 7 hops at 1k to 100k nodes, and still succeed with 30 % churn and
10 % junk answers. Until there are many thousands of full nodes, gossip plus a peers cache is simpler and enough.

## 5. Community relays: "Help the network: relay for others"

**What runs:** the existing `wurelay` with `RELAY_VOLUNTEER=1`. That profile changes only the defaults:

| Setting | Default |
|---|---|
| realms | 25 |
| streams in total | 512 |
| browser streams | 128 |
| KB/s per realm | 256 |
| GB per day per realm | 5 |
| shared 3724 port | off |
| `RELAY_MESH` | on |

Explicit settings win over the profile. The relay publishes a signed relay record with its caps and its live load.

**How a host starts one (the Host pack):**

* `setup.py volunteer-relay --host <public DNS name> [--region eu]` writes `state/volunteer-relay.env`.
* `docker compose -f docker-compose.volunteer-relay.yml up -d` runs the relay plus Caddy for TLS.
* `--off`, and `... down`, stop it.
* The pack now ships `tools/wurelay` and `tools/Dockerfile.relay`: `tools/leyline-repo/hostkit.py` copies them in.

**In the launcher:**

* Settings > Advanced lists the flag "Help the network: relay for others".
* When the website offers it **and** this PC chose "On", a row appears with a public-name box and
  START RELAYING / STOP. That calls `host_volunteer_relay`, which runs `host::volunteer_relay`.
* The website alone never makes a PC relay (`flags::volunteer_allowed`).

**What it needs:** honestly, a reachable PC. Unlike hosting, which is outbound only, relaying for others needs:

* a public DNS name, for TLS;
* TCP 80, 443 and 41000-41051 reachable from the internet, through port forwarding or a public IP.

The NAT check in `p2p/nat.rs` can tell a player up front whether that will work (`open` or
`endpoint_independent`). UPnP port mapping is not built.

**How hosts use them:**

* `setup.py relay-pick [--volunteers]` reads the verified relay records, picks the least loaded relay with room
  (seeds only unless `--volunteers`), and points the realm at it (`relay_url`, `listing_url`, `join_base`).
* The realm's signed beat then names that relay, and that relay attests the endpoint.

**How players pick** (`choose_endpoint` in Python, `choose` in Rust):

* Cost = rtt × (1 + 2 × load), where load = streams / caps.streams.
* A relay that is full of realms costs 40 % more.
* Ties go to the seeds.
* Unmeasured rtt counts as 250 ms. The launcher measures with a TCP connect to port 443, 1.5 s at most.
* Without `mesh_relays`, only the seeds and the realm's own relay are used.
* `browser` keeps only endpoints that serve the WebSocket bridge.

**Fallback order:**

1. direct, when `p2p_hosting` is on and the host allows it (the rule exists; hole punching is not built);
2. a community relay the realm chose;
3. our seed relay.

The realm list falls back the same way: the mesh, then today's network listing, then the relay's own listing,
then the cache.

**Multi-relay agents (designed, not built).** Today an agent dials one relay. The beat format already allows
several (`relays: [...]`), and records keep up to 8 endpoints. Two pieces are missing:

* **an agent that holds two or three tunnels,** and adds one when its relays fill up;
* **a realm-list rewrite on the relay.** The authserver's realm list carries one world address, the primary
  relay's. A player who logs in through relay B would otherwise be sent to relay A for the world server. The relay
  can rewrite the REALM_LIST answer for its own endpoint; `wunet/wire335.py` already parses and builds it.

The simulation shows why this matters: without it, popular realms run out of room (part D).

## 6. NAT traversal (what exists)

`launcher/src-tauri/src/p2p/nat.rs` classifies the network with STUN: open, endpoint-independent, symmetric, or
blocked. `p2p/direct.rs` holds the rule for when a direct connection may replace the relay: the `p2p_hosting`
flag, the host allows it, and the listing advertises it.

* **Not built:** UDP or TCP hole punching, and the agent's direct offer.
* **Without them, "direct" means:** the host opened a port itself.

The mesh doesn't change this. A direct endpoint would be one more endpoint kind, attested by the realm key
itself. Its IP would then be public, by the host's own choice.

## 7. Hopping between realms with your own game files

* **Desktop:**
  1. `realms::pick_client` picks the player's own client for the realm's build. Leyline never downloads a client.
  2. The launcher writes `set realmlist <chosen relay>:<auth port>`.
  3. For a private realm, it knocks at the chosen relay (`POST /api/realms/<id>/knock`).
  4. The account is made on that relay's join page, `https://<relay>/join/<id>`. The password never leaves the
     browser (SRP6).
* **Browser:** the existing hop bridge, `wss://<relay>/ws/<id>/auth` and `/world`, on any relay whose endpoint
  says `"ws": true`.
  * The Origin allow-list (`RELAY_PLAY_ORIGINS`) defaults to our play sites, on community relays too.
  * The browser can only use relays with a valid TLS certificate, which is why community relays run Caddy.

## 8. Abuse and Sybil resistance

| Threat | What stops it today | Gap / next step |
|---|---|---|
| Forged or tampered realm | signatures; tested on both sides | none |
| Keeping a dead realm listed | 15-minute expiry, re-offers refused | none |
| A relay claiming a realm | endpoints count only for relays the realm signed | none |
| Spam realms (keys are free) | only realms with a relay-attested endpoint show as live; relays already cap new realms per IP per hour (`RELAY_NEW_REALMS_PER_IP_HOUR`) and in total | a hostile community relay can attest its own fake realms: staff blocks (below), and per-relay realm caps at the seeds' gossip intake (next step) |
| Fake relays advertising capacity | `relay-pick` defaults to seeds; caps and load are signed but self-reported | a reachability probe before use (fetch `/api/mesh/node` over TLS and compare the key), plus uptime reputation measured by the seeds |
| Flooding a node | 120 pushed records a minute per address, 14 KB bodies, 50 000 records per store, 6 KB per record | per-/24 limits for new relay records |
| Eclipse of a launcher | every refresh includes a seed while seeds exist; three sources merged | with no seeds, peer diversity rules (different /16s) |
| Bad actors, network-wide | `block` records signed by a pinned staff key: dropped and refused everywhere, at most 90 days. `RELAY_BLOCK_FILE` keeps working on our relays | `TODO(owner)`: make the staff key and pin it in `STAFF_KEYS` (Python and Rust). Until then no block is valid. A report from the website feeds the staff, never the mesh directly |

## 9. Privacy: what each party sees, and what is encrypted today

* **The host's IP** is seen by the relay its agent dials, and only by that relay: ours, or the community relay the
  host chose. Players see it only if the host chooses direct. The mesh records carry relay names, never host IPs.
* **A player's IP** is seen by the relay they connect through, never by the host. Our relays log only salted
  daily hashes. A community relay's operator could log more; that is their machine.

**What is encrypted today:**

| Leg | Encrypted? | Notes |
|---|---|---|
| Agent to relay | Yes: TLS (wss) | Terminated at the relay. |
| Browser to relay | Yes: TLS (wss) | Terminated at the relay. |
| Desktop player to relay | **No** | The game's own protocol. The login is SRP6, so the password is never sent. World packets have only their headers encrypted (session key), and the bodies are plain. |

**So a relay, ours or a volunteer's, sees the game traffic in the clear:** chat, whispers, movement. It could even
change packet bodies in flight. It never sees passwords.

That is not "volunteer relays only see encrypted tunnel traffic". The owner's direction asks for that, and **it is
not true yet.**

**The fix (designed, not built): a sealed path.**

* The launcher runs a local proxy for the stock client.
* It opens an end-to-end Noise (XK) session to the host's agent, pinned to the realm key from the signed record.
  The relay then forwards only ciphertext.
* The browser client would do the same inside the page.

**Until that exists, the safe policy is:** keep `mesh_relays` off, so players use only our seeds and the relay
each realm chose itself. Or turn it on with a plain-words notice. That is a decision for the owner (below).

## 10. How the torrent structure fits

Unchanged rules: `p2p/transfer.rs` handles only `Kind`s of open content, and every file passes `p2p/checker.rs`
(the refusal list: game data by name, magic bytes, a client) and a sha256 check. The mesh adds discovery, not new
content:

* **What:** launcher updates, the Host pack, theme packs, and mod packages that passed the Workshop checks.
* **How:**
  * each package already has a single-file `.torrent` web-seeded by its GitHub release (BEP 19, built and tested);
  * a future `package` record kind, signed by the Workshop/staff key, would carry {name, version, sha256, infohash,
    web seeds};
  * relays could also answer as HTTP trackers for those infohashes only.
* **Never:** game data or clients. The record kind, the tracker and the checker each refuse them.
* **Not built:** the peer-wire engine. With `torrent_downloads` on, downloads use the web seeds today.

---

## Scale evidence (simulation)

`python3 hosting/mesh-sim/meshsim.py` (seed 7, about 60 s on this 2-CPU box; `--quick` for 1k and 10k only). It
runs in process, with no network. Results from 2026-10-29:

### A. Gossip: one new record, push to 3 peers plus pull 1 peer every 6 rounds, 24-peer random views, 10 s rounds

| Nodes | Offline (stale views) | Malicious (drop all, push forgeries) | Rounds to 99.9 % | Rounds to 100 % | Messages per honest node | Forgeries received per node per round |
|---|---|---|---|---|---|---|
| 1 000 | 0 % | 0 % | 5 (50 s) | 5 | 6.8 | 0 |
| 1 000 | 30 % | 0 % | 10 (100 s) | 10 | 12.0 | 0 |
| 1 000 | 0 % | 10 % | 7 (70 s) | 7 | 9.1 | 0.36 |
| 1 000 | 30 % | 30 % | 21 (210 s) | 21 | 23.3 | 0.63 |
| 10 000 | 0 % | 0 % | 6 (60 s) | 7 | 9.1 | 0 |
| 10 000 | 30 % | 0 % | 12 (120 s) | 18 | 20.3 | 0 |
| 10 000 | 0 % | 10 % | 7 (70 s) | 9 | 11.4 | 0.30 |
| 10 000 | 30 % | 30 % | 19 (190 s) | 20 | 22.1 | 0.62 |
| 100 000 | 0 % | 0 % | 8 (80 s) | 9 | 11.5 | 0 |
| 100 000 | 30 % | 0 % | 14 (140 s) | 20 | 22.0 | 0 |
| 100 000 | 0 % | 10 % | 9 (90 s) | 11 | 13.2 | 0.30 |
| 100 000 | 30 % | 30 % | 21 (210 s) | 30 | 32.1 | 0.63 |

* **Every run reached every live honest node.**
* **Worst case:** 100k nodes with 30 % offline and 30 % hostile took 3.5 minutes to reach 99.9 %. That is inside
  the 15-minute record lifetime, with room for two refreshes.
* **Forgeries cost little:** honest nodes received under one a round each, and each is dropped after one signature
  check.

### B. The real merge code: `wunet.mesh.Store`, real Ed25519

Setup:

* 300 nodes and 12 realms;
* 30 % of the nodes offline each round, chosen afresh;
* 10 % hostile nodes that push, every round, tampered records, records signed by the wrong key, endpoints on relays
  the realm never chose, and a realm that stopped beating 16 minutes earlier.

Results:

* **270 of 270** honest nodes ended with every realm.
* **0** forged or tampered records accepted; 23 150 refused offers.
* **0** records left once the 15-minute lifetime passed without a refresh.

### C. DHT lookups: Kademlia, k = 8, alpha = 3

| Nodes | Offline | Junk answers | Mean hops | p95 hops | Queries | Found the closest live node |
|---|---|---|---|---|---|---|
| 1 000 | 0 % | 0 % | 4.0 | 4 | 10.8 | 100 % |
| 1 000 | 30 % | 10 % | 5.1 | 8 | 13.6 | 100 % |
| 10 000 | 0 % | 0 % | 4.7 | 5 | 12.8 | 100 % |
| 10 000 | 30 % | 10 % | 5.8 | 9 | 15.9 | 100 % |
| 100 000 | 0 % | 0 % | 5.3 | 6 | 14.8 | 100 % |
| 100 000 | 30 % | 0 % | 5.8 | 7 | 16.5 | 100 % |
| 100 000 | 30 % | 10 % | 7.0 | 11 | 19.2 | 100 % |

### D. Relay choice for 100 000 players, with the real `choose_endpoint`

Setup:

* 2 000 realms, Zipf-popular;
* 70 % of each realm's players are near its host;
* community relays: 512 streams (256 players) and 25 realms each;
* 3 seeds of 4 096 players each;
* the load the players see is stale (refreshed every 2 000 joins).

| Seeds | Community relays | Multi-relay agents (scale-out) | Players served | Share through seeds | Median rtt | Median rtt, seeds only |
|---|---|---|---|---|---|---|
| 3 | 300 | no | 74 606 | 16.5 % | 26.8 ms | 77.1 ms |
| 3 | 300 | yes | 89 026 | 13.8 % | 30.6 ms | 79.8 ms |
| 0 | 400 | no | 70 820 | 0 % | 27.0 ms | n/a |
| **0** | **400** | **yes** | **100 000** | 0 % | 31.3 ms | n/a |
| 0 | 250 | yes | 64 000 | 0 % | 29.7 ms | n/a |
| 0 | 150 | yes | 38 400 | 0 % | 29.2 ms | n/a |

* **Latency:** picking by latency and load cuts the median round trip from about 77 ms to about 27 ms, against
  sending everyone to the nearest seed.
* **Room is a count, not a protocol problem:** 100 000 concurrent players need room for 100 000 × 2 streams. At
  the volunteer defaults that is **about 400 community relays** (or fewer, bigger ones), without any seed.
* **Popular realms need more than one relay.** Without multi-relay agents, 25 to 30 % of players don't fit, even
  when total room exists. With them, every run fills up to the room there is.
* **Our relay today** (`RELAY_MAX_STREAMS_TOTAL` 4096) carries about 2 000 players, and `RELAY_MAX_STREAMS` 128
  caps one realm at 64 players per relay. Both are settings, but they are the real ceiling.

### E. Bandwidth, from real record sizes

A realm record is 1 336 bytes, and about 470 bytes gzipped in a snapshot.

**What gossip costs each full node** (one refresh per realm every 5 minutes, fanout 3):

| Realms | Up and down per node | Snapshot (gzip) |
|---|---|---|
| 1 000 | 13 KB/s | 0.47 MB |
| 2 000 | 26 KB/s | 0.94 MB |
| 10 000 | 130 KB/s | 4.7 MB |

**What launchers cost:** 100 000 launchers, 10 % with the Realms page open, one refresh every 2 minutes, makes 83
snapshots a second network-wide. Spread over the full nodes, that is:

| Full nodes | Per node |
|---|---|
| 5 | 125 Mbit/s |
| 50 | 12.5 Mbit/s |
| 300 | 2.1 Mbit/s |

* **Launchers, not gossip, are the dominant cost.**
* **Levers:**
  * a longer refresh while the page is open;
  * `?since=` deltas;
  * a CDN or Caddy cache in front of the seeds' snapshot (it is already `Cache-Control: public, max-age=30`);
  * splitting the record into "profile" and "presence".

### What the simulation does not prove

* Real networks: NAT, packet loss, TLS handshakes, asymmetric home uplinks, nodes on small CPUs.
* Adaptive attackers: a Sybil flood of the peer view, a targeted eclipse, a relay that attests fake realms of its
  own. The model's hostile nodes drop and forge; they don't adapt.
* The gossip and DHT parts model `meshnode.py`'s policy in numpy. They don't run its HTTP code. The HTTP code is
  covered by the unit and end-to-end tests: two real relays and an agent, in `hosting/tests/test_mesh.py`.
* That 400 people will volunteer. Without volunteers, our seeds are the network.

---

## What is built and what is designed

| Piece | State |
|---|---|
| Record format, signing, verification, expiry, staff blocks, merge rules, bucket summaries (Python) | **Built**, tested (`hosting/tests/test_mesh.py`) |
| The same checks and merge in the launcher (Rust, `ring` Ed25519), plus a cross-language test vector | **Built**, tested (`p2p/mesh.rs`, `p2p/mesh-vector.json`) |
| The relay as a mesh node: push, pull with cursors and epochs, bucket sync, peers cache, `/api/mesh/*`, a realms.json view | **Built**, tested in process and end to end over HTTP (relay A to relay B) |
| Community relay profile: `RELAY_VOLUNTEER`, compose file, Caddy, `setup.py volunteer-relay`, `relay-pick`, Host pack contents | **Built**. The compose file has not been run on a real PC with open ports. |
| Launcher: the realm list from the mesh, a relay chosen per realm, peers cache, fallback to today's listings | **Built**, tested |
| Launcher toggle and START/STOP (`host_volunteer_relay`) | **Built**. The command compiles only with the `app` feature, which was not built here. |
| Multi-relay agents and the realm-list rewrite on the relay | Designed |
| Sealed path (end-to-end encryption past the relay) | Designed |
| DHT | Designed, simulated |
| Hole punching, UPnP | Not built |
| `package` records and relays as trackers | Designed |

## The flags, and the order to turn them on

**Server side:**

* `RELAY_MESH=1` on our relay (`hosting/relay/deploy/relay.env`). Optionally set `RELAY_NODE_KEY`; the default is
  `node.key` next to the state file.
* The site flags are in `stream/leyline_net.py KNOWN`, written by the admin console.
* The launcher overrides are in Settings > Advanced.

**The order:**

1. **`RELAY_MESH=1` on relay.openvanilla.app.** Check that `/api/mesh/node` answers, and that
   `/api/mesh/realms.json` lists the same realms as `/api/listing/realms.json`.
2. **`mesh_realms` on the site.** Launchers then read the list from the mesh. Any failure falls back to today's
   listings, so this is low risk.
3. **Host pack release, then `relay_volunteer` on the site.** That offers "Help the network". Players still use
   only the seeds and each realm's own relay.
4. **`mesh_relays` on the site,** only after the sealed path exists, or after the owner accepts the privacy
   trade-off in section 9. From then on, players use community relays when they are closer.
5. **`p2p_hosting`** is independent of the mesh (direct connections).

**Backward compatibility:** the new flags change the flags file's sha256, and old launchers still verify it,
because the hash covers the whole document. Old launchers ignore unknown flags.

## Decisions for the owner

* **The staff key.** Make it and pin it in `STAFF_KEYS`, in both `wunet/mesh.py` and `p2p/mesh.rs`. Until then
  network-wide blocks can't be issued.
* **The seed list and seed keys.** Name more seed relays (`SEEDS`), and pin each seed's node key (`SEED_KEYS`).
* **Community relays and privacy.** Either wait for the sealed path before `mesh_relays`, or turn it on with a
  plain notice that the relay can see game chat.
* **Our relay's caps.** At today's caps our relay carries about 2 000 players, and one realm at most 64 players.
  Raise them, add seeds, or rely on volunteers.
* **Volunteers need open ports.** Is "Help the network" for players who can open ports, or should UPnP be built?
* **Next to build:** multi-relay agents plus the realm-list rewrite. That is what lets popular realms grow past one
  relay.
