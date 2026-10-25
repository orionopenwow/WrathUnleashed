# Making minigolf courses for Leyline

Minigolf is the first **mode** on Leyline's play layer. A course is a small text file. The browser client builds it in front of the players, and every shot plays out identically on every screen. No model files, no client patches, no Blizzard assets: a course is pure geometry you describe.

- **Play:** `/golf` in game. *Play here* opens a game where you stand and invites your party; *Practice* plays solo anywhere.
- **Engine:** `crates/benilla-mode/src/golf.rs` (client source). The format below is that file's parser.
- **Referee:** `realm/custom/lua_scripts/ov_golf.lua`. **HUD:** `WrathUnleashedUI/Golf.lua`.

## The format

There is one instruction per line, and `#` starts a comment. Units are yards and degrees. Every hole is played on the same spot, so holes replace each other: build each one around `tee 0 0 0` looking down **+z**. **+x** is to the right and **+y** is up.

```text
course My Course          # the title (48 characters max)
by YourName               # credit (32 max)

hole 3 The Long Way       # par (1-9), then the hole's name
tee  0 0 0                # where the ball starts (a point ON the surface)
cup  2 0 14               # the cup (a point ON the surface)
turf 0 -0.25 7   1.5 0.25 8          # a block: centre x y z, half-sizes x y z, [yaw] [pitch]
```

| Instruction | Arguments | What it does |
|---|---|---|
| `turf` `sand` `ice` | centre x y z, half x y z, [yaw°], [pitch° up to ±45] | Ground. Turf rolls normally, sand stops the ball fast, ice barely slows it. A negative pitch tilts the block up toward +z, which makes a ramp. |
| `wall` | same as a block | Timber walls that bounce the ball back. |
| `bump` | base x y z, radius, height | A springy round post that kicks the ball off harder than it arrived. |
| `water` | surface x y z, half x, half z | A hazard. A ball that drops in costs **+1** and goes back to where it was hit from. |
| `boost` | centre x y z, half x, half z, yaw°, speed | A pad that pushes the ball along its yaw up to `speed` yd/s. |
| `spin` | centre x y z, half x y z, degrees per second | A bar that turns about its own centre (windmills, turnstiles). |
| `slide` | centre x y z, half x y z, travel x, travel z, seconds | A block that slides to centre + travel and back once every `seconds`. |

**Tips**
- **Surfaces:** a block's top is at `centre y + half y`. To put the playing surface at y = 0, use `turf 0 -0.25 … 0.25 …`, as the shipped course does.
- **Walls:** about `0.1` thick and `0.4` half-high is a good default. Close every edge you don't want the ball to leave by. Off the course is **+1** too.
- **Ramps:** a ramp rising `h` over a run of `d` has pitch `-atan(h/d)` and half-length `sqrt(d²+h²)/2`. Put its centre a quarter-yard below the middle of its top surface along the normal. "Up the Ramp" in `meadow-nine.course` is a worked example.
- **Spinners and sliders** follow a shared clock that the realm sends with every shot, so their timing is fair and identical for everyone.
- **Limits:** 18 holes, 160 pieces per hole, 24 KB of text, coordinates within ±80 yd. A stroke cap of par + 4 (max 9) keeps a hole from going on forever.

## Check that a course is playable

From the client source:

```sh
cargo run --release -p benilla-mode --example golf_probe path/to/my.course    # best line per hole
cargo run --release -p benilla-mode --example golf_window                      # how forgiving Meadow Nine is
```

The probe searches aims and powers stroke by stroke and prints how many strokes the best line takes on each hole. `NOT HOLED` means a hole can't be finished. That usually means a missing floor, a cup inside a wall, or a ramp that's too steep for full power.

## Put a course on a realm

1. Create `realm/custom/lua_scripts/ov_golf_courses.lua`:
   ```lua
   return {
       { key = "mycourse", text = [==[
   course My Course
   by YourName
   hole 2 Opener
   tee 0 0 0
   cup 0 0 10
   turf 0 -0.25 5  1.5 0.25 6.5
   ]==] },
   }
   ```
2. Reload the realm's scripts. The course appears in everyone's `/golf` window, and parties play it together.

Workshop publishing (upload, review, one-click Play) is the next milestone. Courses will arrive on realms through this same file.

## Fair play

- Shots are two integers: aim in tenths of a degree, and power in permille.
- Every client simulates the roll with the same deterministic code. Wasm and native are checked bit for bit by `scripts/golf-determinism.sh`.
- Every client reports the roll's hash. If two clients disagree, the realm announces it, keeps the shooter's result, and doesn't count the round as verified.
- Only rounds with two or more players and no disagreement are verified in `mod_golf_scores`.
- Solo rounds are recorded but unverified. A certifying host that replays shots on the server side is planned.
