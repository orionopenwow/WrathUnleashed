# Soak plan: 50 headless players, 1 hour, through the relay

Goal: before opening hosting to everyone, show that one relay + one home-hosted realm carry 50
concurrent players for an hour with no stuck streams, no tunnel drops and acceptable latency, and
that the relay's caps and memory stay flat.

## Setup (needs the owner's OK: it uses the relay VM)
1. Relay deployed (`relay/deploy/deploy-relay.sh`), raise the test realm's caps for the run only:
   `RELAY_MAX_STREAMS_PER_IP=200 RELAY_MAX_STREAMS_PER_IP_TOTAL=200 RELAY_CONN_PER_MIN_PER_IP=1000`
   (all 50 players come from one load machine's IP), restart the relay.
2. A host (the owner's PC or a spare box) runs the kit, profile `brawl` (instant 80, cheap
   characters), public, `WU_BOTS=40`.
3. 50 accounts: `for i in $(seq -w 1 50); do bash host-wrath-realm.sh friend SOAK0$i soakpass1; done`
   (Windows: `Realm tools.bat friend SOAK001 soakpass1` ...).
4. Load machine: any Linux box with Python 3.10+, NOT on the host's network (a second VM).

## Run
```
python3 tests/soak/soak.py --auth relay.openvanilla.app:<auth_port> --clients 50 \
        --duration 3600 --ramp 120 --ping 25 --relog 600 --accounts SOAK --password soakpass1 > soak.json
```
Each player logs in, enters the world, pings every ~25 s (CMSG_PING round trip), logs out and in
again every ~10 minutes (exercises auth + world reconnects through the relay). While it runs:
- every 5 min: `curl -s http://127.0.0.1:8080/metrics` on the relay (streams open, bytes, refusals),
  `docker stats --no-stream` on the relay and the host;
- once at 30 min: kill the host's agent container (`docker restart wu-host-agent`): players drop,
  the tunnel must be back within 60 s and players log in again on their own (counted as errors
  for that window only);
- once: `Check my realm.bat` on the host during load.

## Pass criteria
| Metric | Pass |
|---|---|
| login success (outside the agent-restart window) | ≥ 99 % |
| ping p95 / p99 added by relay + tunnel (compare with a direct LAN run) | ≤ 60 ms / ≤ 150 ms |
| relay RSS | flat (± 20 %) after the ramp; no growth over the hour |
| `wu_relay_streams_open` after the run | 0 (nothing leaked) |
| tunnel reconnects | only the forced one |
| relay CPU | < 25 % of one core |
| traffic | ≈ 2 × players × game rate; inside `RELAY_KBPS` (no shaping kicked in) |

## Harness self-test (done here)
`python3 tests/soak/soak.py --rig --clients 50 --duration 120 --ramp 20 --ping 5 --relog 40`:
in-process relay + agent + fake realm. Result in `RESULTS.md` (151 logins, 0 errors, p99 ping
1.2 ms). This checks the harness and the relay's multiplexing under 50 concurrent sessions, not
the network: the real run above does that.
