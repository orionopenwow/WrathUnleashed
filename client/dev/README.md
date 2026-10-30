# Client dev helpers

Scratch helpers for building and boot-checking the browser client. Moved here from the repo root on 2026-10-30.

- `rebuild.sh`: the lighter dev build of the wasm client (expects the client tree in `bw/`, wasi-sdk in
  `wasi/` and a `smoke/` folder beside it; adjust the paths for your checkout).
- `smoke-serve.py` + `smoke.js`: the data-free boot check. Serve a build with `python smoke-serve.py dist`
  (port 8091), then run `node smoke.js` (needs Playwright). It should boot to the login screen.
