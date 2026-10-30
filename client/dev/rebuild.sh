set -e
cd "$(dirname "$0")/bw"
WASI_SDK=$(cd ../wasi/wasi-sdk-27.0-x86_64-linux && pwd) RUSTC_BOOTSTRAP=1 CARGO_INCREMENTAL=0 CARGO_TARGET_DIR=../tbw CARGO_TARGET_WASM32_UNKNOWN_UNKNOWN_RUSTFLAGS="-C target-feature=+simd128" cargo +stable build -j2 --config 'profile.dev.debug=0' -Z build-std=std,panic_abort --target wasm32-unknown-unknown -p wenilla --no-default-features --features webgpu --message-format short 2>&1 | grep -E "^crates.*(error|warning)|^error|Finished" | cut -c1-250
cd ..
~/.cargo/bin/wasm-bindgen --target web --no-typescript --out-dir dist tbw/wasm32-unknown-unknown/debug/wenilla.wasm
cd smoke && timeout 150 node smoke.js 2>&1 | grep -v "wasm-function\|^\s*$\|^Stack:\|^Error$\|__wbg_new" | head -60
