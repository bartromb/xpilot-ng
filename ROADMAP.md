# XPilot NG Modernization Roadmap

Goal: revive XPilot NG 4.7.3 (last release 2010, C, GPLv2) so it builds and runs
cleanly on modern Linux (Ubuntu 24.04+, Wayland, current GCC/Clang), then
incrementally modernize the client.

Repo: **`bartromb/xpilot-ng`** (https://github.com/bartromb/xpilot-ng) — this is where the
modernization work lives, and it is what `origin` points at.

Upstream provenance: the code originates from the SourceForge 4.7.3 tarball, by way of the
GitHub mirror `kekyo/xpilot-ng`, which this repo is a fork of and which is wired up as the
`upstream` remote. Upstream is archival — it has seen no development since 2010 — so treat it
as a provenance link and a source of history, never as a merge target.

## Ecosystem — state of play (checked Aug 2026)

Upstream and forks, so we know what exists before reinventing it:

- **XPilot NG** — the codebase this project revives. Last release 4.7.3 (2010);
  development dead. xpilot.org survives as an archive (maps, recordings, docs).
- **BloodsPilot** (SourceForge) — fork optimized for the Blood's Music map; own
  client, server and metaserver. Development dormant, but a residual community
  still exists (forum: xpilot.ktd.krakow.pl, activity as recent as 2026).
  - Their **metaserver was forked to GitHub**: `lmartinking/xpilot-metaserver`,
    written in Python → prime starting point for the Phase 5 metaserver
    replacement instead of building from scratch.
- **xpilot.io** (`mpdairy/xpilot.io`) — the only actively developed relative:
  a browser XPilot rebuild, v2 rewrite in Rust + WASM, driven with Claude Code
  (has its own CLAUDE.md and roadmap). Rebuilds the *concept*, not the original
  protocol/codebase — complementary, not competing. Worth reading their
  CLAUDE.md before starting Phase 0, and their `xpilot_maps.md` covers the .xp
  map format.
- **XPilot5** — complete C++ rewrite from the 2000s; dead. Ignore.
- **wpilot** (`jfd/wpilot`) — 2010 Node.js/HTML5 proof-of-concept browser
  remake; abandoned. Ignore.
- **Not the game**: the GitHub user "XPilot" and the `xpilot-project` org
  (VATSIM X-Plane pilot client) are unrelated — don't confuse them in searches.

Positioning: this project is the only active effort to modernize the original
C codebase while keeping compatibility with 30 years of maps, replays and the
original protocol.

How to use this file with Claude Code: work one phase per session. Start each
session with "Read ROADMAP.md, we are in Phase N" and end it by asking Claude to
update the checklist and the Status Log below. Each phase should end in a
commit (or merged branch) with a working build.

---

## Phase 0 — Baseline: make it compile at all

Branch: `phase0-baseline` (in practice the compile fixes landed on `master` via the merged
`feature/fix-compilation` branch — no `phase0-baseline` branch was ever created)

- [x] Import 4.7.3 source into a fresh git repo (upstream import is the first commit, `db31540`)
- [x] Document build deps in `BUILDING.md` (X11 dev headers, expat, zlib, SDL 1.2, OpenGL, OpenAL)
- [x] Run `./configure && make`, capture ALL errors/warnings into `build-log-baseline.txt`
- [x] ~~Fix autoconf breakage on modern autotools~~ — **not needed**: the shipped `configure`
      runs clean as-is. autoconf/automake are not even installed here, so `autoreconf -fi` was
      never required. Revisit only if `configure.ac` has to change.
- [x] Fix C errors from modern GCC defaults — landed before this session in
      `feature/fix-compilation`; verified 0 errors with GCC 13.3
- [x] Get `xpilot-ng-server` running headless with robots as smoke test
- [x] Get the X11 client connecting to localhost server
- [x] Commit: "builds on Ubuntu 24.04 with GCC 14" — committed with the message corrected
      to say GCC 13.3, which is what was actually verified

Acceptance: **MET** — `make` succeeds with zero errors, and a local game against 4 robots ran
the full 5 minutes with no crash on either side.

### Verified baseline (25 Aug 2026)

Environment: Linux Mint 22.2 (Ubuntu 24.04 base), GCC 13.3.0 — note this is **GCC 13, not 14**,
so the planned commit message overstates the coverage. SDL 1.2 is supplied by `sdl12_compat`
(an SDL2-backed shim), not real SDL 1.2.

All five binaries build and run:

| Binary | State |
|--------|-------|
| `src/server/xpilot-ng-server` | runs headless, 50 fps, loads maps, spawns robots |
| `src/client/x11/xpilot-ng-x11` | connects, logs in, renders ("pixmap copying") |
| `src/client/sdl/xpilot-ng-sdl` | connects, logs in, loads textures, GL 8/8/8 depth 24 |
| `src/replay/xpilot-ng-replay` | builds (not exercised) |
| `src/mapedit/xpilot-ng-xp-mapedit` | builds (not exercised) |

Build warnings: 55 total, no errors —
25 `-Wdiscarded-qualifiers`, 8 `-Wunused-result`, 1 `-Wpointer-to-int-cast`, rest uncategorized.
Worst offenders: `forms.c` (20), `file.c` (11), `SDL_console.c` (3), `clientcommand.c` (3).
Full log in `build-log-baseline.txt`; still needs distilling into `docs/warnings-debt.md`.

Audio is **compiled out**: `config.h` has `#undef SOUND`. Two reasons, both worth knowing —
sound is opt-in (`--enable-sound`, not passed), *and* OpenAL/freealut are not installed here.
`configure` treats missing audio libs as non-fatal, so `--enable-sound` on this machine would
still yield a silent build with only a warning. Nothing links freealut today, so Phase 3
starts from "no audio" rather than from a live dead-library port — confirm the intended
starting point before scoping that phase.

**Gotcha that costs an hour if you hit it cold:** the server exits cleanly (rc=0) as soon as
the last *human* player disconnects. A second client started afterwards just prints
"Retrying..." forever against a server that is no longer there, which looks exactly like a
broken client. Always smoke-test with `-noQuit -idleRun`:

```
./src/server/xpilot-ng-server -map lib/maps/dodgers-robots.xp2 \
    -maxRobots 4 -minRobots 4 -port 15000 -noQuit -idleRun &
./src/client/sdl/xpilot-ng-sdl -join -name test -port 15000 localhost
```

Note the client takes the host as a positional arg with `-port` separate; `localhost:15000`
is *not* parsed and fails with "Can't find the server".

Two more traps when scripting the smoke test:

- **Checking liveness.** `pgrep -f xpilot-ng-server` is useless — it matches the enclosing
  `timeout N ./src/server/xpilot-ng-server ...` wrapper (which outlives the server) *and* the
  shell command doing the checking, so it reports "alive" against a dead server. `pgrep -x
  xpilot-ng-server` never matches either, because Linux truncates `comm` to 15 chars. Use
  `pgrep -x xpilot-ng-serve` (note: no trailing `r`) or, better, `ss -ulnp | grep :15000`.
- **Killing it.** For the same truncation reason `pkill -x xpilot-ng-server` silently kills
  nothing; and `pkill -f xpilot-ng-server` will kill the shell running the command, since that
  shell's own command line contains the pattern. Kill by saved PID.

Everything in Phase 0 is now done. `docs/warnings-debt.md` (a standing-instructions artifact,
not a Phase 0 checklist item) is still outstanding.

## Phase 1 — Build system: autotools → CMake

Branch: `phase1-cmake`

- [ ] Inventory what autotools actually detects/configures (write to `docs/build-audit.md`)
- [ ] Write top-level `CMakeLists.txt` covering server + X11 client first
- [ ] Add SDL client target behind an option flag
- [ ] Keep the autotools build working in parallel until CMake reaches parity
- [ ] Add a GitHub Actions CI workflow: build server + clients on ubuntu-latest
- [ ] Remove autotools once CI is green on CMake only

Acceptance: `cmake -B build && cmake --build build` produces the same binaries; CI passes.

## Phase 2 — Client: SDL 1.2 → SDL2

Branch: `phase2-sdl2`

- [ ] Audit SDL 1.2 API usage in the SDL client (`grep -rn "SDL_" src/client/sdl/` → categorized list)
- [ ] Port video: `SDL_SetVideoMode` → `SDL_Window` + `SDL_GL_CreateContext`
- [ ] Port event loop (keysym changes, text input API, window events)
- [ ] Port surfaces/blitting used for HUD and textures
- [ ] Handle high-DPI and window resize properly
- [ ] Verify fullscreen toggle, alt-tab, multi-monitor on Wayland (XWayland is fine as intermediate step)
- [ ] Retire the raw X11 client OR keep it compiling but mark unmaintained

Acceptance: SDL2 client plays a full robot match on Wayland with correct input and no rendering glitches.

## Phase 3 — Audio: OpenAL/freealut → SDL2_mixer (or miniaudio)

Branch: `phase3-audio`

- [ ] Map current sound events → sample table
- [ ] Replace freealut loading (dead library) with SDL2_mixer
- [ ] Positional audio: simple stereo panning based on screen position is enough
- [ ] Make audio optional at build AND runtime (server stays silent/headless)

Acceptance: all game sounds play; build no longer links freealut.

## Phase 4 — Quality of life

Branch: per-feature (`phase4-<feature>`)

- [ ] Scalable HUD/fonts for 1440p/4K
- [ ] Config: respect XDG dirs (`~/.config/xpilot-ng/`) instead of `~/.xpilotrc` (with migration)
- [ ] Modern keybind defaults + in-client remapping
- [ ] Gamepad support via SDL2 GameController API
- [ ] Package: .deb via CPack, optionally Flatpak manifest

## Phase 4b — Graphics modernization

Branch: per-feature (`phase4b-<feature>`)

Hard rules for every item in this phase:
- Presentation only — never alter perceived hitboxes, positions, or timing. Glow/particles
  must not visually shift where an object "is".
- Every effect individually toggleable at runtime; a single "classic" render mode disables
  them all and reproduces the plain vector look.
- Server untouched. All work lives in the SDL2 client.

- [ ] Layered glow via additive blending (same primitive drawn 2-3x, increasing width,
      decreasing alpha) for ships, walls, shots — no shaders required
- [ ] Particle system: thrust exhaust, explosions, debris (client-side, driven by
      existing server events only)
- [ ] Parallax starfield, 2-3 depth layers
- [ ] Polish the existing SDL texture mode for ships/walls instead of rebuilding it
- [ ] Later / stretch: OpenGL 3.3 core shader pipeline with bloom post-processing
- [ ] Later / stretch: dynamic lighting — shots and explosions tinting nearby walls

Acceptance: robot match looks visibly modernized with all effects on; "classic" mode is
pixel-comparable to the pre-4b renderer; toggling any effect mid-game causes no
gameplay-visible change; stable 144 fps on modest hardware with all effects enabled.

## Phase 5 — Network & multiplayer revival (optional/later)

- [ ] Audit UDP protocol for NAT-friendliness; document in `docs/protocol.md`
- [ ] Self-hostable metaserver replacement (tiny HTTP JSON service) since original metaservers are dead
- [ ] systemd unit + Docker image for easy server hosting (LAN games at home)
- [ ] Security pass on server input parsing (1990s C parsing network packets — fuzz it: AFL++ on packet handlers)

---

## Phase 6 — AI players (builds on Phase 5 protocol docs)

Branch: separate repo or `ai/` subtree — Python, not C. Server stays untouched;
bots are external clients speaking the documented network protocol (same
information a human player gets — no reading internal server state).

### 6a — Python bot SDK (first milestone)
- [ ] Implement the client network protocol as a Python library (`xpilot_bot`):
      connect/join, decode game state into typed dataclasses, send actions
      (turn / thrust / fire / special)
- [ ] Headless operation — no rendering dependency
- [ ] Example bots: `idle`, `wanderer`, simple rule-based `hunter` (~20 lines each)
- [ ] Smoke test in CI: bot joins local server, survives 60s against 2 robots

### 6b — Gymnasium environment
- [ ] Wrap the SDK in a Gymnasium interface: `reset()`, `step(action)`,
      observation space, reward function
- [ ] Use the server FPS option to run training at 10-20x realtime
      (prior Xpilot-AI research relied on variable-framerate training)
- [ ] Parallel environments: N servers + N bot clients per training run

### 6c — Learned agents
- [ ] Baseline: PPO via Stable-Baselines3, self-play
- [ ] Curriculum: navigate-only map → dodge → combat (prior work shows direct
      combat learning stalls; staged rewards needed)
- [ ] Benchmark against the built-in server robots; log win rates per checkpoint
- [ ] Stretch: LLM as high-level strategy layer / chat personality on top of a
      classical controller (never for frame-level control — latency unsuitable)

Acceptance 6a: a third party can `pip install` the SDK and have a moving,
shooting bot on a local server in under 30 minutes using only the README.

## Standing instructions for Claude Code sessions

- C, GPLv2 — all new/modified files keep GPLv2 headers.
- Never do Phase 2+ work while Phase 0/1 is incomplete on the branch.
- Prefer minimal diffs over rewrites; this codebase has 30 years of gameplay tuning in it — do not "clean up" physics/gameplay constants.
- Every session: build + run the robot smoke test before declaring done.
- Warnings policy: new code compiles clean with `-Wall -Wextra`; legacy warnings tracked in `docs/warnings-debt.md`, reduced opportunistically.

## Status Log

| Date | Phase | Session summary | Commit/branch |
|------|-------|-----------------|---------------|
| 2026-08-25 | 0 | Audited actual build state against the checklist. `./configure && make` clean: 0 errors, 55 warnings, all 5 binaries built. Server + both X11 and SDL clients verified against a local 4-robot game; 5-minute soak passed, so Phase 0 acceptance is met. Found the server exits when the last human leaves (`-noQuit` needed) and that audio is compiled out (no OpenAL headers). Wrote `BUILDING.md` and closed out Phase 0. No C source was touched this session — the compile fixes were already on `master`. | `phase0-baseline` (docs only; branched from `b7a6905`) |
