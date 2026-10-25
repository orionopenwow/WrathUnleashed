# Test results (2026-10-24, this sandbox: Python 3.13, no Docker daemon)

## Unit and integration tests: 46 passed (twice: `cryptography` Ed25519 and the pure-Python fallback)
`cd hosting/tests && python -m pytest -v`. Real relay + real agent + fake AzerothCore 3.3.5a
(tests/fake_realm.py: SRP6 server side, realm list, auth challenge, session digest, RC4 headers,
char enum/create, login, a 40 KB packet with the 5-byte header, time sync, ping, logout) + the
real headless client (kit/tools/wunet/wire335.py). test_relay.py ran 3 more times in a row: no flakes.

```
test_crypto.py::SRP::test_handshake_and_wrong_password PASSED            [  2%]
test_crypto.py::SRP::test_interleave_known_answer PASSED                 [  4%]
test_crypto.py::SRP::test_matches_owner_account_maker PASSED             [  6%]
test_crypto.py::SRP::test_verifier_golden PASSED                         [  8%]
test_crypto.py::SRP::test_x_known_answer PASSED                          [ 10%]
test_crypto.py::Cipher::test_ends_agree PASSED                           [ 13%]
test_crypto.py::Cipher::test_hmac_rfc2202 PASSED                         [ 15%]
test_crypto.py::Cipher::test_rc4_rfc6229 PASSED                          [ 17%]
test_crypto.py::Keys::test_realm_id PASSED                               [ 19%]
test_crypto.py::Keys::test_sign_verify_both_backends PASSED              [ 21%]
test_crypto.py::FakeRealmLogin::test_direct_full_run PASSED              [ 23%]
test_e2e_client.py::E2EClientScript::test_private_then_public PASSED     [ 26%]
test_join_page.py::JoinPageSRP::test_js_verifier_matches PASSED          [ 28%]
test_join_page.py::JoinPageServed::test_relay_serves_join_page PASSED    [ 30%]
test_relay.py::Public::test_browser_websocket_path PASSED                [ 32%]
test_relay.py::Public::test_login_through_relay_per_realm_port PASSED    [ 34%]
test_relay.py::Public::test_many_players_multiplexed PASSED              [ 36%]
test_relay.py::Public::test_shared_port_needs_a_knock PASSED             [ 39%]
test_relay.py::Public::test_status_and_metrics PASSED                    [ 41%]
test_relay.py::Private::test_knock_then_tcp_works_and_new_secret_locks_out PASSED [ 43%]
test_relay.py::Private::test_private_needs_the_secret PASSED             [ 45%]
test_relay.py::Accounts::test_signup_from_join_page_then_play PASSED     [ 47%]
test_relay.py::Accounts::test_signup_rate_limit_and_off PASSED           [ 50%]
test_relay.py::Caps::test_bandwidth_is_shaped PASSED                     [ 52%]
test_relay.py::Caps::test_connection_rate PASSED                         [ 54%]
test_relay.py::Caps::test_daily_quota PASSED                             [ 56%]
test_relay.py::Caps::test_idle_streams_are_closed PASSED                 [ 58%]
test_relay.py::Caps::test_slow_player_is_cut_not_the_tunnel PASSED       [ 60%]
test_relay.py::Caps::test_stream_caps PASSED                             [ 63%]
test_relay.py::Tunnel::test_agent_reconnects_with_same_ports PASSED      [ 65%]
test_relay.py::Tunnel::test_agent_waits_for_database PASSED              [ 67%]
test_relay.py::Tunnel::test_bad_logins_refused PASSED                    [ 69%]
test_relay.py::Tunnel::test_new_agent_replaces_old PASSED                [ 71%]
test_relay.py::Tunnel::test_relay_restart_keeps_ports PASSED             [ 73%]
test_relay.py::Blocklist::test_blocked_realm_is_cut_refused_and_delisted PASSED [ 76%]
test_relay.py::Listing::test_heartbeat_listing_and_claim PASSED          [ 78%]
test_relay.py::Listing::test_listing_rules PASSED                        [ 80%]
test_selfcheck_ws.py::SelfCheck::test_all_good_private PASSED            [ 82%]
test_selfcheck_ws.py::SelfCheck::test_problems_are_plain PASSED          [ 84%]
test_selfcheck_ws.py::WebSocketEdges::test_echo_text_binary_and_sizes PASSED [ 86%]
test_selfcheck_ws.py::WebSocketEdges::test_fragmented_message_with_ping_between PASSED [ 89%]
test_selfcheck_ws.py::WebSocketEdges::test_handshake_errors PASSED       [ 91%]
test_selfcheck_ws.py::WebSocketEdges::test_oversize_is_refused PASSED    [ 93%]
test_selfcheck_ws.py::WebSocketEdges::test_unmasked_client_frame_is_refused PASSED [ 95%]
test_setup.py::Setup::test_admin_commands PASSED                         [ 97%]
test_setup.py::Setup::test_init_and_rerun PASSED                         [100%]
============================= 46 passed in 22.26s ==============================
```

Pure-Python Ed25519 run: 46 passed in 21.70s

## Harness soak: 50 clients, 2 minutes, in-process (relay + agent + fake realm)
`python tests/soak/soak.py --rig --clients 50 --duration 120 --ramp 20 --ping 5 --relog 40`
All 50 in the world at once on one tunnel, 151 full sessions (login, world, enter, pings, logout),
0 errors. Ping = CMSG_PING round trip through relay + tunnel + fake worldserver on loopback.
```
{
 "clients": 50,
 "duration_s": 126,
 "logins": 151,
 "completed_sessions": 151,
 "peak_in_world": 50,
 "login_ms": {
  "p50": 7.9,
  "p95": 11.7,
  "max": 19.3
 },
 "ping_ms": {
  "n": 1112,
  "p50": 0.4,
  "p95": 0.6,
  "p99": 1.2,
  "max": 6.7,
  "mean": 0.5
 },
 "errors": {},
 "relay": {
  "agent_logins": 1,
  "streams_opened": 302,
  "bytes": 6194411,
  "streams_closed": 301
 }
}
```

## The docker e2e player script against an in-process rig (test_e2e_client.py)
```
PASS realm online at the relay
PASS unknocked IP refused (private)
PASS wrong invite refused
PASS websocket without invite refused
PASS invite link lets this IP in
PASS account made from the join API
PASS login + char create + enter world + logout (per-realm port)
PASS same through the shared port 3724
PASS same over the WebSocket path (browser client)
PASS status.json through the relay
{"mode": "private", "ok": true, "passed": 10, "failed": []}
```
then the public phase (fresh account path, Beacons listing via signed heartbeat): pass.

## Other checks
- `docker compose config` validates `kit/docker-compose.host.yml` (with a generated .env and the
  real profiles), the e2e override merge, and `relay/deploy/compose.yml`.
- `bash -n` on every .sh; `host-wrath-realm.sh` dry-run (`WU_DRY=1`, fake docker) walks setup ->
  images -> data -> start -> profile SQL -> relay -> invite without errors.
- `server/set-realm-address.sh --relay STATE_DIR` and the port check run against a fake docker.
- The join page's JS SRP6 verifier (node 22) equals AzerothCore's math and benilla-srp's golden.

## Not run here (needs Docker or the owner's OK)
- `tests/e2e/run-e2e.sh --fake` (CI) and `--real` (owner's PC: real AzerothCore + ov-client-data).
- A real 3.3.5a Wow.exe login through the relay (see INSTALL-OPERATE 7.1: `realmlist host:port`).
- The 1-hour soak on the relay VM (tests/soak/SOAK-PLAN.md).
