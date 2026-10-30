# P2P and torrent in Leyline: built, tested, OFF

**Peer-to-peer and torrent transfers in Leyline never carry game data and never carry a game client.**

They may carry only these:
* Leyline itself (launcher updates);
* mod packages that passed the Workshop checker;
* theme packs;
* the Host pack.

The download path has a closed list of kinds (`transfer::Kind`). Every file, whatever way it arrived, goes
through the refusal list (`p2p/checker.rs`) and a sha256 check:
* **By name:** archives, textures, models, maps, databases (`.mpq .blp .m2 .wmo .adt .dbc .db2 .skin .anim
  .wdt .wdl .bls .casc`).
* **By magic bytes:** `MPQ\x1a`/`MPQ\x1b`, `BLP1/2`, `MD20/21`, `WDBC`/`WDB2`, `REVM`.
* **By being a client:** the game's executables, a game `Data/` folder, `_retail_`/`_classic_` folders.

A refused file is deleted and never installed. The same list runs when the Host pack is built
(`hosting/pack/make-hostpack.py`).

## The switches

Everything ships **off**. Two layers decide:

1. **The site's file**, `https://play.openvanilla.app/wrath/leyline/flags.json`:

   ```json
   {
    "format": 1,
    "updated_at": "2026-10-29T00:00:00Z",
    "flags": {"p2p_hosting": false, "torrent_downloads": false, "torrent_seeding": false, "webrtc_presence": false,
              "mesh_realms": false, "mesh_relays": false, "relay_volunteer": false},
    "limits": {"seed_upload_kbps": 0, "seed_ratio_pct": 0, "max_peers": 0},
    "stun": ["stun.cloudflare.com:3478"],
    "sha256": "<hex>"
   }
   ```

   * **The hash:** `sha256` is the SHA-256 of the canonical JSON of the document without `sha256`. In Python
     that is `json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`, encoded as UTF-8.
   * **Bad files:** the launcher recomputes the hash. A missing, broken or mismatching file counts as
     **all off**. The last good copy is cached for offline use.
   * **What the hash is for:** it guards against corruption and half-written files. Authenticity comes from
     HTTPS to our own site. Signing the file with an Ed25519 site key is a possible later step.
   * **Limits:** they are capped (upload 100 000 KB/s, ratio 1000 %, 200 peers). Unknown flags are ignored.
2. **This PC's overrides**, in **Settings > Advanced: peer-to-peer**, saved in
   `<app data>/Leyline/leyline-flags-local.json`.
   * Each flag is either "Follow the website", "On on this PC" or "Off on this PC".
   * A local choice wins over the site's, both ways: a player can switch off something the site turned on,
     or try something early.
   * The upload limits can be set here too.

| Flag | What it turns on | Status |
|---|---|---|
| `p2p_hosting` | **Direct connections to hosted realms.** The NAT check (STUN) runs, and a realm may be reached directly when both sides allow it. The relay is always the fallback. | Rule and NAT check built and tested. The agent's direct offer and hole punching are not built yet. |
| `torrent_downloads` | **BitTorrent downloads** for our packages: first the swarm, then the torrent's HTTP web seeds (checked piece by piece), then plain HTTPS. | Metainfo, web seeds, piece check and fallback built and tested. There is no peer-wire engine yet (see below). |
| `torrent_seeding` | **Sharing downloaded packages back.** | Needs `torrent_downloads`, this flag, an upload cap above 0 and a ratio above 0. It can do nothing until a peer engine is plugged in. |
| `webrtc_presence` | **Friends online over a direct browser link.** | Flag only: reserved for the social agent's work. |
| `mesh_realms` | **The realm list from the Leyline mesh**: signed records from peers and the seed relays, verified in the launcher. Falls back to today's listings. | Built and tested (`p2p/mesh.rs`, docs/LEYLINE-MESH.md). |
| `mesh_relays` | **Community relays** may carry this PC's game traffic when closer. Off: only our seeds and each realm's own relay. | Built and tested. Relays see game traffic in the clear until the sealed path exists (docs/LEYLINE-MESH.md section 9). |
| `relay_volunteer` | **"Help the network: relay for others" is offered.** A PC relays only when this PC is also set to "On". | Built (Host pack compose file, `host_volunteer_relay`). |

### For the admin console

`stream/leyline_net.py` has the writer:

```python
import leyline_net
leyline_net.write_flags(leyline_net.path(), {"torrent_downloads": True}, by="<admin account>")
leyline_net.write_flags(None, {}, limits={"seed_upload_kbps": 512, "seed_ratio_pct": 150})
```

* It refuses unknown flags and anything that is not `True`/`False`.
* It writes atomically to `$WU_LEYLINE_DIR/flags.json`, which defaults to `/data/leyline`, that is
  `$WU/portal-data/leyline` on the box: wu-portal's one writable mount.
* It appends one JSON line per change to `flags.json.log` (who, when, what). The served file never names the
  admin.
* `leyline_net.load()` returns the current document, or the all-off defaults.

## Torrent downloads: what is real and what is not

**Built and tested (unit tests, local fixtures, no internet seeds):**
* single-file `.torrent` parsing;
* strict bencode;
* the info-hash;
* web seeds (BEP 19 `url-list`);
* the per-piece SHA-1 check;
* the sha256 check against the catalog;
* the refusal list;
* the HTTPS fallback;
* a `Swarm` trait that a real engine plugs into.

`make-hostpack.py` writes a matching torrent for every Host pack, with the release file as its web seed, so
any standard BitTorrent client can seed it today.

**Not built:** the BitTorrent peer protocol (BEP 3 peers, trackers, DHT) inside the launcher. The built-in
`NoSwarm` has no peers. With the flag on, a torrent download therefore comes from its web seeds, which are our
own HTTPS files, and is checked against the torrent's piece hashes.

**Why not a crate now:** the pure-Rust option is `librqbit` (rqbit). It builds on Windows, macOS and Linux,
but it brings a large async stack (tokio, its own HTTP stack and DHT) and network-facing code into a small
launcher. We would also be shipping an engine nobody can switch on yet. The plan is to add it behind a cargo
feature (`torrent-engine`) as a `Swarm` implementation once the flag is going to be switched on. It would use
the upload cap, ratio and peer limits from `flags::Limits`, and seed only files that passed the checks above.

## Direct connections: the rule

Today every player reaches a hosted realm through the relay. The relay hides the host's home address and
works behind any router.

A direct connection shows each side the other's IP address. So `p2p::direct::decide` picks it only when all of
these hold:
* the flag is on;
* the host allows it;
* the player allows it;
* both NAT checks say a direct path can work (no NAT, or endpoint-independent mapping);
* the host's address is a real public one.

Otherwise it is the relay, with a reason in plain words.

**The listing side (2026-10-29), also off.** A host allows direct connections with "Allow direct connections" on
the Host page (`direct` in `state/beacon.json`, default false). The relay lists `community.directConnect: true` only
when its operator sets `RELAY_ADVERTISE_DIRECT=1` (default 0) and the host allows it; the launcher shows "Direct
connect available" only when `p2p_hosting` is on. No address is published in the listing: the endpoint exchange
stays for `p2p::direct`, behind the same rule.

The NAT check (`p2p::nat`) uses STUN Binding requests (RFC 5389) to up to two servers from the flags file. It
runs only when `p2p_hosting` is on. The STUN server sees the PC's public IP address, as any website does.

## Tests

`cargo test --no-default-features` covers everything with the flags off and on:
* bencode and torrent vectors;
* SHA-1 FIPS vectors;
* web seed, good and bad pieces;
* a fake swarm, honest and lying;
* game data and a client refused with the flags off and on;
* sha256 required and checked;
* STUN against local fake servers (endpoint-independent, symmetric, one answer, none);
* the direct rule;
* the flags hash, tamper detection, cache and local overrides.

The flags hash vector (`9a48f487…`) is the same in the Rust and Python tests.
