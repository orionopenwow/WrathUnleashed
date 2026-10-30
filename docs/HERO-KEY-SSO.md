# Hero Key sign-in for Beacons (cross-server login)

One identity, the Hero Key (the website account at play.openvanilla.app), signs a player in to any community realm
(Beacon) on the Leyline network. No account per realm, no password kept in the browser. It works in the browser game
(a Leyline hop) and in the launcher.

Status: built and tested. Off until the owner turns it on (see "Turning it on"). With it off, nothing changes: hops
use the realm's join page and the login kept in `localStorage`, as in `docs/leyline-realm-hopping.md`.

## How it works

```
 player's browser / launcher          website (portal)             relay                 realm's agent (Beacon)
 ---------------------------          ----------------             -----                 ----------------------
 signed in with Hero Key  ──────────▶ issue(account, realm id)
                                      sub = per-realm pseudonym
                                      one-time password P (random)
                                      SRP salt+verifier of P
                                      assertion signed with the
                         ◀──────────  site key (Ed25519)
 { assertion, sig } + P
 POST assertion ─────────────────────────────────────────────────▶ /api/realms/<id>/herokey
                                                                     (rate limits)  ──────▶ herokey_login:
                                                                                            check signature (pinned key),
                                                                                            audience, expiry, nonce;
                                                                                            account HK<sub> made or found;
                                                                                            salt+verifier set;
                         ◀───────────────────────────────────────────── ok ◀─────────────── expires after login_ttl
 game client: SRP login as HK<sub> with P, through the relay as always (3.3.5a protocol unchanged)
```

1. **The site issues an assertion.** `stream/herokey_sso.py`. For one Hero Key account and one realm id it makes:
   - `sub`, a pseudonym: `base32(HMAC-SHA256(pepper, "leyline-sso-sub-v1\n" + realm id + "\n" + ACCOUNT))[:26]`.
     The same every time for this player on this realm; a different, unrelated value on every other realm.
   - a one-time password `P` (16 characters, random), made for this sign-in only. It is not stored.
   - the assertion, signed with the site key (context `leyline-herokey-sso-v1`):

     ```
     {"v": 1, "iss": "play.openvanilla.app", "kid": "<16 hex>", "aud": "<realm id>", "sub": "<26 base32>",
      "salt": "<64 hex>", "verifier": "<64 hex>", "login_ttl": 120, "nonce": "<32 hex>", "iat": <unix>, "exp": iat+120}
     ```

     `salt` and `verifier` are the SRP6 values of `P` for the account `HK` + the first 14 characters of `sub`,
     upper case (AzerothCore's 32 little-endian bytes).
2. **The player's side redeems it at the relay.** `POST https://<relay>/api/realms/<id>/herokey {assertion, sig}`.
   The relay checks the shape and that `aud` is this realm, applies its rate limits, and passes it to the realm's
   agent (control op `herokey_login`). It can't read `P`: it only ever sees the verifier.
3. **The realm's agent checks and maps.** `hosting/kit/tools/wunet/herokey.py` (the check) and
   `wuhost/agent.py` (`herokey_login`). It verifies the signature against the site key pinned in the host kit, then
   `aud` = its own realm id, `iat`/`exp` (60 s clock skew, at most 5 minutes' lifetime), and that the nonce is new.
   It derives the account name from `sub` itself. First time: it makes the account (fails with `taken` if an account
   of that name exists that it did not make for a Hero Key). Later: it sets the new salt and verifier. It records
   only `sub -> account` in `state/herokey-accounts.json`. After `login_ttl` seconds it replaces the verifier with a
   random one, so `P` stops working. A player already in the world stays in (the world server checks the session
   key, not the verifier).
4. **The client logs in as usual.** SRP to the realm through the relay, with `HK...` and `P`. The 3.3.5a client and
   protocol are unchanged.

What each party sees:

| | Hero Key / site password | global account id | `sub` / `HK...` | `P` | verifier |
|---|---|---|---|---|---|
| Website | yes (it is the identity provider) | yes | yes | made there, not stored | yes |
| Player's browser / launcher | its own | no (not in the assertion) | yes | yes | yes |
| Relay | no | no | yes | **no** | yes |
| Realm (host) | no | no | yes | **no** | yes |

### In the browser game (a hop)

- `stream/wrath_portal.py` `hop_env`: with the flag on, a hop to a Beacon (not the Dalaran Hangout, which already
  uses the Wrath login) gets `hop_sso: {assertion, sig, redeem}` and the one-time login in `user`/`pass`.
- `stream/www-files/wrath-early.js` (the leyline-hop block): checks that `redeem` is this realm's route on the same
  relay as the bridge, posts the assertion (`credentials: "omit"`), and holds the client's start (its wasm download)
  until the realm answered, at most 8 s. No join page; nothing written to `localStorage`.
- Any refusal (the realm doesn't take Hero Key sign-in, offline, rate limit, timeout) falls back to the old flow: the
  login this browser keeps for the realm, else the framed join page.
- **Use another account** (the hop bar) turns Hero Key sign-in off for that realm in this browser
  (`localStorage["wu.leyline.sso.off.<id>"] = "1"`) and shows the join page, which then offers **Sign in with your
  Hero Key** to turn it back on.

### In the launcher

- `launcher/src-tauri/src/herokey.rs`: `request` (the site's `POST /wrath/api/social/herokey {realm}`, with the
  launcher's own revocable token from the Friends sign-in), `redeem` (the relay), `set_account_name` (writes
  `SET accountName "HK..."` into the client's `WTF/Config.wtf`).
- `app.rs` `play_realm_herokey`: the flag on, the realm a live community realm, then sign in, write the account name,
  point the client at the realm and start it. The 3.3.5a client can't take a password from outside, so the Realms
  page shows the one-time password to type. It works for 10 minutes (`login_ttl` 600 for the launcher) and is not
  saved anywhere.
- `ui/app.js`: a **Sign in with your Hero Key** button on live community realm cards, only with the flag on.

### Realm hosts

- Opt in: `setup.py herokey on` (host.json `"herokey": true`). Off by default.
- It only starts once the kit pins the website's key (`wunet/herokey.py` `SITE_KEYS`, or `WU_HEROKEY_SITE_KEYS`).
  Until then the agent refuses every assertion (`off`) and doesn't advertise it.
- With it on, the agent's hello to the relay carries `"herokey": true`; `GET /api/realms/<id>` shows it.
- Ban a player's pseudonym: add its `sub` to host.json `"herokey_banned": [...]`.
- Cap the login window: host.json `"herokey_login_ttl_max"` (seconds, at most 900).
- Works on every core the kit supports (`set_login` in `agent.RealmDB` and `coredb.py`).

## The flag

`herokey_sso`, declared like the other Leyline flags: `stream/leyline_net.py` `KNOWN` (the admin console's flags
page, owner only, typed confirm), `launcher/src-tauri/src/p2p/flags.rs` `KNOWN` (a local override in Settings >
Advanced wins). Default off. With it off:

- `/__env.js` is exactly as before (no `hop_sso`, no login for a Beacon).
- `GET /wrath/leyline/herokey.json` is 404; the launcher call answers 404; no key files are made.
- The launcher shows no Hero Key button and `play_realm_herokey` refuses.
- The relay route exists but answers 403 `off` for every realm that has not opted in; an agent without the opt-in
  sends the same hello as before.

Turning it off again takes effect at once (the portal reads the flags file on every use).

## Threat model

**Replay.** Each assertion has a random nonce, a 2-minute `exp` and an audience. The agent keeps used nonces until
they expire and refuses a second use (`replay`); a bad signature never spends a nonce, so junk can't fill the cache.
Even a successful replay would only set again the verifier the real player already knows: the attacker still lacks
`P`. After `login_ttl` the verifier is scrambled. The nonce cache is in memory: an agent restart inside the 2-minute
window forgets it (the replay would still be harmless for the same reason). TODO(owner): persist the cache if that
matters.

**A malicious realm.** It sees only its own pseudonym `sub`, the account name made from it, and a verifier for a
one-time password. It cannot sign in elsewhere as the player: `aud` binds the assertion to its realm id, `sub` is
different on every realm, and `P` is unique per sign-in. It can do what any realm can to its own accounts (refuse,
ban, log what the player does there). It can't learn the Hero Key, the site password or the global account id. A
realm that lies about its id can't get assertions for another realm's id without that realm's key: the relay routes
by the id the agent proved with its Ed25519 realm key.

**Relay MITM.** The relay terminates TLS and sees the assertion and, later, the SRP exchange. It cannot learn `P`
(it gets only the verifier; `P` has about 80 bits of entropy, so the verifier can't be reversed), and it cannot swap
in its own verifier or point the assertion at another account: every field is signed. It could drop or delay the
sign-in (denial of service) or replay it (see Replay). A relay that sees the SRP exchange learns no more than with a
join-page account today. A community relay (`mesh_relays`) is in the same position.

**The website.** It is the identity provider and could sign in as any player anywhere; that is the trust Hero Key
holders already place in it. It never stores `P`. The site key and the pepper sit in `/data/leyline`
(`herokey-site.key`, `herokey-pepper.key`, 0600, made on first use, never printed or logged), beside the other portal
data, and are covered by its backups. TODO(owner): whether to move them to a secrets store or an HSM.

**Key rotation and revocation.**
- Rotation: put the new key in `herokey-site.next.key`; `herokey.json` then lists both (`current`, `next`). Ship a
  kit with both public keys in `SITE_KEYS`, wait for hosts to update, then swap the files. Assertions name the key
  they were signed with (`kid`), so both work during the overlap. TODO(owner): the overlap period and how hosts are
  told to update.
- A leaked site key: remove it from `SITE_KEYS` and ship a kit update; until hosts update, a realm accepts it. TODO(owner):
  a signed revocation list the agent fetches, or a kit auto-update for this one value.
- Per player: the realm host can ban a `sub` (`herokey_banned`). The player can decline Hero Key sign-in for a realm in
  this browser ("Use another account"). Revoking the launcher's token on `/wrath/link` stops its sign-ins.
- The whole feature: the `herokey_sso` flag (site), `setup.py herokey off` (realm).

**Privacy (per-realm ids).** `sub` is an HMAC under a pepper only the website holds, so two realms comparing notes see
unrelated ids and account names; nothing else in an assertion repeats across realms (fresh salt, verifier and nonce).
The relay sees which realm ids one IP signs in to, as it sees which realms an IP connects to today. Changing the
pepper changes every player's account on every realm (their characters stay on the old accounts). TODO(owner): an
opt-in "show my Hero Key name to this realm" (linking across realms) is not built; it would add a separate, signed
claim the player chooses per realm.

**Rate limits.**
- Website: 60 assertions an hour per account (`herokey_limit`), plus a global ceiling; `/__env.js` is already rate
  limited per IP.
- Relay: `RELAY_HEROKEY_PER_IP_MIN` (20) per IP and `RELAY_HEROKEY_PER_REALM_MIN` (120) per realm, per minute.
- Realm: the agent only makes an account for a valid, signed assertion, so account creation is bounded by the
  website's limit per player. TODO(owner): a per-realm cap on new Hero Key accounts per day (the join page has
  `RELAY_ACCOUNTS_PER_REALM_DAY`).

**Name squatting.** A join-page account named like `HK...` blocks that player on that realm (`taken`), but guessing
another player's 70-bit name is not practical. The agent never takes over an account it did not make for a Hero Key.

**Clock skew.** 60 seconds each way. A realm whose clock is far off refuses assertions (`early` / `expired`); the
hop falls back to the join page.

## Open questions for the owner

- TODO(owner): turn on `herokey_sso`, then copy the `pub` from `GET /wrath/leyline/herokey.json` into
  `hosting/kit/tools/wunet/herokey.py` `SITE_KEYS` and release the kit. Order matters: the key is made on first use
  after the flag is on.
- TODO(owner): the launcher's one-time password is shown on screen for the player to type (10 minutes). Alternatives:
  copy it to the clipboard, or a longer window.
- TODO(owner): whether realms should be able to opt in to "Hero Key only" (no join page), the design doc's
  `signup: "herokey"`. Today it is a separate switch next to `signup`.
- TODO(owner): linking a player across realms on request (see Privacy).
- TODO(owner): revocation beyond a kit update (see Key rotation).
- TODO(owner): the `docs/leyline-realm-hopping.md` design had the player derive a per-realm key from their own Hero
  Key secret. This build uses a website-signed assertion instead: the website already holds the Hero Key sign-in, the
  browser needs no new crypto, and the launcher needs no SRP code. The per-realm unlinkability is the same.

## Tests

- `hosting/tests/test_herokey_sso.py`: sign and verify (both Ed25519 backends), expiry and clock, wrong audience,
  replay, tampering by a relay, an unpinned key, per-realm ids, the key files; end to end with the real relay, agent
  and the headless 3.3.5a client logging in through the browser bridge; refusals (expired, `taken`, banned, rate
  limit); off by default; on in host.json but no pinned key.
- `stream/tests/test_hop.py`: the hop env with the flag off (unchanged) and on (assertion, one-time login, never the
  Wrath login), the public key, the launcher call, rate limit, back off.
- `stream/tests/test_social.py`: the launcher route (Bearer token, flag off).
- `stream/tests/hop.page.test.cjs`, `stream/tests/hop-frame.browser.test.cjs`: redeem before start, fallback,
  "Use another account", bad tickets ignored, flag off unchanged, CORS from the game page to the real relay.
- `launcher/src-tauri/src/herokey.rs` tests, `p2p/flags.rs` (off by default), `launcher/tests/realms.browser.test.cjs`.

## Where it deploys

| Part | Files | Autopilot step |
|---|---|---|
| Website: issue, `herokey.json`, the hop env, the launcher route, the flag | `stream/herokey_sso.py`, `stream/wrath_portal.py`, `stream/social.py`, `stream/leyline_net.py` | signin (portal) |
| Game page: redeem and fallback | `stream/www-files/wrath-early.js`, `stream/www-files/wrath-page.js` | signin (portal; the page layer ships with the stream site) |
| Relay: the route and its limits | `hosting/relay/wurelay/relay.py` | relay |
| Realm agent and kit: check, accounts, opt-in, pinned key | `hosting/kit/tools/wunet/herokey.py`, `wuhost/agent.py`, `wuhost/coredb.py`, `wuhost/setup.py` | hostkit |
| Launcher: command, button, flag | `launcher/src-tauri/src/herokey.rs`, `app.rs`, `social.rs`, `p2p/flags.rs`, `launcher/ui/app.js` | leyline |
