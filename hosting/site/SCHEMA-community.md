# Beacons: community records (proposed addition to `www/realms/SCHEMA.md`)

Home-hosted public realms are not files in `www/realms/`. The relay's listing serves them:

```
GET https://relay.openvanilla.app/api/listing/realms.json      (CORS *, max-age 30)
{ "schema": 1, "kind": "community", "updated": "2026-10-24T20:00:00Z", "realms": [ <record>, ... ] }
```

Each record is a schema-1 Beacon record (same fields, same meaning), built by the listing itself,
plus one block. Readers that don't know `community` can show the record as is.

| Field | Value for community records |
|---|---|
| `slug` | `c-<realm id>` (realm id = 16 base32 characters from the realm's Ed25519 key) |
| `official` | always `false` |
| `state` | `live` while heartbeats arrive (3 missed beats = `offline`); gone after 24 h |
| `order` | always `1000`: below official realms; then live first, then by name. Never paid, never voted. |
| `profile.address` / `port` | the relay's name and the realm's own relay auth port |
| `profile.ruleset` | `main`, `brawl`, `progression` (the host's profile) |
| `connect` | `{"kind": "web-signin", "url": "https://openvanilla.app/join/<id>", "label": "Join this realm"}` |
| `status` | `{"url": "https://relay.openvanilla.app/r/<id>/status.json", "format": "openvanilla-status-1"}` |
| `media` | empty: no host-supplied images or links are shown in v1 |

```json
"community": {
  "realmId": "k3x9q2m4p7w8r5t2",
  "relay": "relay.openvanilla.app",
  "signed": true,
  "claimed": false,
  "claimedBy": null,
  "firstSeen": "2026-10-24T18:00:00Z",
  "lastSeen": "2026-10-24T20:00:00Z",
  "lastHeartbeat": { "online": true, "players": 3, "bots": 40, "uptime_s": 7200 }
}
```

- Show `claimed: false` as "Unclaimed"; `claimedBy` is the Hero Key account's display name.
- Text comes from the host (name ≤ 32, tagline ≤ 80, summary ≤ 400, up to 10 rules ≤ 120,
  discord only as `https://discord.gg/...`), whitespace-collapsed by the listing. Render as text,
  never as HTML.
- Population: live from `status.url` as for official realms; `lastHeartbeat` is the fallback.
  Bots are never added to players.
