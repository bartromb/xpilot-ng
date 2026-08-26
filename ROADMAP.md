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

- [x] Inventory what autotools actually detects/configures (written to `docs/build-audit.md`)
- [x] Write top-level `CMakeLists.txt` covering server + X11 client first
- [x] Add SDL client target behind an option flag (`XPILOT_SDL_CLIENT`, default ON)
- [x] Keep the autotools build working in parallel until CMake reaches parity
- [x] Add a GitHub Actions CI workflow: build server + clients on ubuntu-latest
- [x] Remove autotools once CI is green on CMake only — done on `phase1-remove-autotools`:
      66 files deleted (`configure`, `configure.ac`, `aclocal.m4`, 27 `Makefile.am` and 27
      `Makefile.in`, `config.h.in`, `bootstrap`, `kps_configure.sh`, `config/` aux scripts and
      the tracked `autom4te.cache/`), plus the parity CI job.

Acceptance: **met.** `cmake -B build && cmake --build build` produces the same binaries
(verified below), and CI passes on ubuntu-latest. Phase 1 is complete.

### Verified parity (25 Aug 2026)

The CMake build was checked against the autotools build on the same machine:

| Check | autotools | CMake |
|---|---|---|
| Binaries produced | 5 | 5, same names |
| Build errors | 0 | 0 |
| Warnings | 55 | 55 |
| Warning categories | 25 `discarded-qualifiers`, 8 `unused-result`, 1 `pointer-to-int-cast` | identical |

The identical warning profile is the strongest evidence of parity available without
comparing binaries byte for byte: the same translation units are being compiled with
equivalent flags. Beyond that, the CMake-built server plus both clients were run through
the Phase 0 smoke test — server with 4 robots, both clients connecting and logging in —
and the autotools build was rebuilt afterwards to confirm the two coexist.

Option paths were exercised rather than assumed: a server-only configuration
(`-DXPILOT_X11_CLIENT=OFF -DXPILOT_SDL_CLIENT=OFF -DXPILOT_REPLAY=OFF
-DXPILOT_MAPEDIT=OFF`) configures and builds without needing X11 or SDL at all, and
`-DXPILOT_SDL_GAMELOOP=ON` compiles `gameloop.c` where the default compiles
`gameloop_x.c`, matching `COND_SDL_GAMELOOP`.

### Autotools removal

Done last, only after CI had been green twice. Checks that made it safe:

- No build target was lost. `contrib/xpngcc`, `src/replay/tools` and the `NT/` directories
  are `EXTRA_DIST` only — they ship in the tarball but nothing compiles them — so the five
  ported executables really were the whole build. The one genuine casualty is `make dist`
  for source tarballs; CPack in Phase 4 replaces it.
- The install tree was captured before deleting anything and diffed against the CMake tree
  afterwards: still 99 files, no differences.
- A clean rebuild after removal still gives 0 errors and the same 55 warnings in the same
  categories.

`src/common/version.h` is now a plain checked-in header rather than a generated one. It is
deliberately **not** regenerated by CMake: it carries the authors' names in ISO-8859-1
(Björn Stabell, Juha Lindström, Kristian Söderblom), and routing it through
`configure_file` would risk silently re-encoding them. Instead CMake parses the version out
of it at configure time and fails if it disagrees with `project(VERSION)`, so the two cannot
drift. That guard was tested by deliberately breaking it.

Structural notes:

- Binaries go to `build/bin/`, not next to their sources. The `BUILDING.md` smoke-test
  commands work unchanged if you substitute that path.
- `CONF_DATADIR` propagates to every target through an INTERFACE target. This is
  self-checking: `xpconfig.h` has `#error "CONF_DATADIR NOT DEFINED"`, so a successful
  compile proves the define reached every translation unit.
- `src/common/version.h` is checked into git and byte-identical to what autotools
  regenerates, so CMake uses it as-is instead of generating it. Resolve when autotools goes.
- `src/replay` needs `src/client` on its include path (for `recordfmt.h`) but does not link
  `libxpclient`. The autotools build did this through the deprecated `INCLUDES` variable,
  which is easy to miss when reading `Makefile.am`.

**Install parity is exact.** Installing both builds to staging roots and diffing the file
lists gives 99 files each and no differences. Getting there caught three things a glob-based
port would have silently got wrong: autotools ships only 12 of the 18 maps on disk, it
installs `ConsoleFont.bmp` (which an `*.ttf` filter misses), and it installs five man pages
plus `mapconvert.py` that are easy to forget entirely. The CMake data lists are therefore
copied verbatim from the `lib/*/Makefile.am` `xpilot*_DATA` variables rather than globbed.

**CI: first run failed, now fixed — second run pending.** The workflow was pushed and did
run. The autotools parity job passed; the CMake job failed at the client smoke test for
three separate reasons, all real:

- The runner has no X11 bitmap fonts, so the X11 client could not load
  `-*-fixed-bold-*` and logged errors. Fixed by installing `xfonts-base`.
- Nothing had been installed, so `CONF_DATADIR` pointed at an empty
  `/usr/local/share/xpilot-ng/` and the clients could not find their textures. Fixed by
  running `cmake --install` before the smoke test, which exercises the install rules too.
- The assertion itself was wrong. It grepped the *client's* stdout for "Login allowed", but
  the client block-buffers stdout and `timeout` SIGTERMs it without a flush, so the line is
  not reliably there even on success. Now it greps the *server* log for the client's
  nickname, which is written by a still-running process and is the authority on who
  connected. Nicknames had to be shortened too — the server truncates them to 15 characters,
  so `ci-xpilot-ng-x11` would never have matched.

The second run is **green**: both the CMake job and the autotools parity job pass, including
the headless client smoke tests under `xvfb-run` with software GLX. Run
[32898668656](https://github.com/bartromb/xpilot-ng/actions/runs/32898668656).

## Phase 2 — Client: SDL 1.2 → SDL2

Branch: `phase2-sdl2`

- [x] Audit SDL 1.2 API usage in the SDL client → `docs/sdl2-port-audit.md`
- [x] Port video: `SDL_SetVideoMode` → `SDL_Window` + `SDL_GL_CreateContext`
- [x] Port event loop (keysym changes, text input API, window events)
- [x] Port surfaces/blitting used for HUD and textures
- [x] Handle high-DPI — the window is created with `SDL_WINDOW_ALLOW_HIGHDPI`, `draw_width`/
      `draw_height` now track `SDL_GL_GetDrawableSize`, and mouse events are scaled from logical
      units to drawable pixels. **See the caveat below: this has no visible effect on X11.**
- [ ] Window resize "properly" — resize works and re-lays out correctly, but leaves black
      artifacts in regions that were not repainted. Verified **pre-existing** (the same artifacts
      appear on the pre-HiDPI build), so not a port regression. The client deliberately clears
      with a full-screen quad rather than `glClear`, only when `damaged <= 0`; that conditional
      is the likely culprit and is where to start.
- [ ] Verify fullscreen toggle, alt-tab, multi-monitor on Wayland — **not done, and blocked by
      the default game loop.** `gameloop_x.c` selects on the X connection fd, so it needs an X11
      video driver; it now says so and points at `-DXPILOT_SDL_GAMELOOP=ON` rather than failing
      obscurely. Native Wayland needs either that option verified or the X11 loop retired.
- [ ] Retire the raw X11 client OR keep it compiling but mark unmaintained

Acceptance: SDL2 client plays a full robot match on Wayland with correct input and no rendering glitches.

### What the audit changed about this phase (26 Aug 2026)

Full detail in `docs/sdl2-port-audit.md`; the two things that alter the plan:

**The client already runs on SDL2.** `libsdl1.2-dev` on Ubuntu 24.04 is `sdl12-compat`, a shim
over SDL2. So this phase does not buy "works on SDL2" — it buys access to APIs the shim cannot
expose (high-DPI, real window events, `SDL_TEXTINPUT`, GameController). Worth keeping in mind
when deciding how much shim-compatible code is worth rewriting: the answer is "only what blocks
those capabilities".

**Most of the work is deletion, not porting.** 77% of `src/client/sdl/` is vendored 1.2-era
third-party code, and it is barely used:

| Vendored | Lines | Actually used | Disposition |
|---|---|---|---|
| `SDL_gfxPrimitives.c` + font header | 6,764 | 3 call sites | swap for packaged `libsdl2-gfx` (same function names) |
| `scrap.c` | 651 | 4 functions | delete — SDL2 has a clipboard API |
| `SDL_console.c` + `DT_drawtext.c` | 1,372 | 14 entry points | port properly |

Roughly 7,400 of 8,787 vendored lines can go. Only 58 call sites across 11 files need changing,
and 60 of the 99 SDL symbols in use are unchanged in SDL2.

Keybindings are **not** a compatibility risk: they are stored by name and resolved through a
table, so SDL2 renumbering `SDLK_*` does not break existing `~/.xpilotrc` files.

### Port landed (26 Aug 2026)

The client links libSDL2 directly; all 58 call sites are ported and `scrap.c` is deleted.

Verified by **A/B against the pre-port build**, built from master in a git worktree and
screenshotted the same way against the same map: the two render identically — same viewport
geometry, score panel, radar, HUD placement, buttons, both at ~50 FPS. Static UI regions differ
only by anti-aliasing from the newer FreeType. A clean rebuild gives 52 warnings in exactly the
same categories as before, so the port introduced none.

### High-DPI: done, but it changes nothing on X11 (26 Aug 2026)

The plumbing is correct and is what Wayland and macOS need. On **X11 it is inert**, and it is
worth being blunt about why, because the reference machine is exactly the case you would expect
it to help:

```
video driver : x11
window size  : 800x600
drawable size: 800x600
scale        : 1.000 x 1.000
display DPI  : ddpi=185.1 hdpi=185.1 vdpi=185.4
```

That panel is 185 DPI — HiDPI by any measure — yet SDL2 on X11 reports drawable == window and a
scale of exactly 1.0. SDL2 does per-window HiDPI scaling on Wayland and macOS only; on X11 the
game already renders at native pixel density, which is precisely why the UI looks small.

**So the visible "everything is tiny on a HiDPI screen" problem is not this checklist item at
all — it is the Phase 4 item "Scalable HUD/fonts for 1440p/4K".** No amount of Phase 2 drawable
-size work will change it on X11. Worth reordering Phase 4 accordingly.

Verified no 1x regression: static UI regions (buttons, score header) are **pixel-identical**
before and after, 0 differing pixels; only the live HUD values differ.

Two findings worth carrying forward:

- **`SDL_Rect` fields are `int` in SDL2**, not `Sint16`/`Uint16`. `glwidgets.c` held a `Sint16 *`
  pointing into a rect and the compiler caught it. Any other code taking the address of a rect
  field needs the same check.
- **Packaged SDL2_gfx is not a drop-in** for the vendored `SDL_gfxPrimitives`, contrary to what
  the audit first claimed — it draws through an `SDL_Renderer`, which this client does not have.
  The vendored copy needed two one-line fixes and was kept. Deleting its 6,764 lines is still
  worth doing but means a software renderer or reimplementing two functions.

## Phase 3 — Audio: OpenAL/freealut → SDL2_mixer (or miniaudio)

Branch: `phase3-audio`

- [ ] Map current sound events → sample table
- [ ] Replace freealut loading (dead library) with SDL2_mixer
- [ ] Positional audio: simple stereo panning based on screen position is enough
- [ ] Make audio optional at build AND runtime (server stays silent/headless)

Acceptance: all game sounds play; build no longer links freealut.

## Phase 4 — Quality of life

Branch: per-feature (`phase4-<feature>`)

- [x] Scalable HUD/fonts for 1440p/4K — new `uiScale` option in the SDL client. `0` (the
      default) auto-detects from the display DPI: 1.0 on an ordinary monitor, ~2.0 on a HiDPI
      panel. Any explicit value overrides. It scales the game and map fonts, the score list
      font and panel, and `hudSize`. Verified on the 185 DPI reference display: auto picks 2.0
      and the interface becomes readable, while `-uiScale 1.0` is pixel-identical to the
      previous build. Fixed a latent bug it exposed: the FPS and lag readouts were spaced by a
      hardcoded 20 pixels and overlapped as soon as the font grew; they now space by font
      height. Known limit: changing `hudScale` at runtime recomputes `hudSize` without the UI
      scale, so that needs a restart to reapply.
- [x] Config: respect XDG dirs (`~/.config/xpilot-ng/`) instead of `~/.xpilotrc` (with
      migration). Resolution order is `$XPILOTRC`, then
      `$XDG_CONFIG_HOME/xpilot-ng/xpilotrc`, then the legacy `~/.xpilotrc`, which is copied to
      the XDG location the first time it is found alone. The original is deliberately kept so a
      downgrade still works. Lives in the shared `option.c`, so the X11 client gets it too. A
      missing config is now INFO rather than the ERROR it used to print on every launch.
- [x] In-client remapping — console commands `/keys [filter]`, `/bind <option> <key>`,
      `/save`, `/help`. Anything not starting with `/` is still chat. Verified end to end by
      driving the console with synthetic key events: bind, save, restart, and the binding is
      read back.
- [ ] Modern keybind defaults — **deliberately not done.** Changing defaults alters muscle
      memory built over 30 years, and the standing instruction is to prefer minimal diffs.
      Remapping is now available for anyone who wants different keys.
- [x] Gamepad support via SDL2 GameController API — `src/client/sdl/gamepad.c`. Buttons and
      axes map onto the existing `Key_press`/`Key_release` action API, with hotplug handled and
      a dead zone on the sticks. **The mapping is unit-tested (21 checks) but has never seen a
      real controller** — no gamepad is attached to the reference machine — so the choice of
      which button does what is unvalidated in play, even though the plumbing is not.
- [x] Package: .deb via CPack — `cpack -G DEB` from the build directory produces
      `xpilot-ng_4.7.3_amd64.deb` (~2 MB, 5 binaries, 5 man pages, all data files).
      Dependencies are derived by `dpkg-shlibdeps` from what actually got linked rather than
      hand-maintained, which is also a useful check on the port: the generated Depends line
      names libsdl2, not SDL 1.2. Verified by extracting the package and running the server
      out of it against its own packaged map.
- [ ] Flatpak manifest — not done. It was optional in this list; a `.deb` covers the
      immediate need and Flatpak wants a manifest plus a runtime choice worth deciding
      deliberately.

## Phase 4b — Graphics modernization

Branch: per-feature (`phase4b-<feature>`)

Hard rules for every item in this phase:
- Presentation only — never alter perceived hitboxes, positions, or timing. Glow/particles
  must not visually shift where an object "is".
- Every effect individually toggleable at runtime; a single "classic" render mode disables
  them all and reproduces the plain vector look.
- Server untouched. All work lives in the SDL2 client.

- [x] Layered glow via additive blending — **walls and ships**, in
      `src/client/sdl/effects.c`. Shots are **not** glowed: they are textured sprites drawn
      through `Image_paint`, whose `frame` argument is an animation index, not a size, so
      there is no way to draw them larger without new geometry. That belongs with the
      particle work rather than here. Ships only glow in vector mode; with `texturedShips`
      on (the default) they are sprites and the same limit applies. Cloaked and phased ships
      are deliberately excluded — a halo would reveal a ship that is meant to be hard to see,
      which would be a gameplay change, not a presentation one.
      Options: `glowEffect` (on), `glowWidth` (1.5), `glowLayers` (3), plus `classicRender`
      as the master off switch. All changeable at runtime with the new `/set` console
      command.
      Verified against the hard rules: the halo is drawn on the *same* geometry with a wider
      line, so the centre — and therefore the apparent position — cannot move; with robots
      disabled the scene is deterministic, and classic mode differs from the pre-4b build by
      **fewer pixels than the pre-4b build differs from itself between runs** (21,865 vs
      26,499 of 1.31M), while glow differs by 63,531; and `/set glowEffect no` mid-game drops
      brightness from 2.65 to 1.57, matching classic.
- [x] Particle system — implemented as an **afterglow trail** rather than a simulation, and
      that choice is deliberate. The server already decides where every spark and debris
      fragment is on every frame; a client-side simulation would draw things at positions the
      server never sent, which this phase's rules forbid. Instead each spark leaves a fading
      mark at the position the server actually reported, so the trail is the spark's own
      history. One mechanism covers thrust exhaust, explosions and debris, because all three
      already arrive as sparks.
      Options: `particleEffect` (on), `particleLife` (350ms). Fixed 8192-particle pool,
      overwritten oldest-first, so a firefight cannot make the client allocate unboundedly.
      Ageing uses wall-clock time, so a trail lasts the same duration at 50 or 144 fps.
      Verified visually: thrusting produces a clear exhaust plume marking the ship's path.
      **Performance is not yet validated.** The reference machine was under heavy external
      load (8 unrelated CPU-saturated processes, load average 9) during measurement, so
      absolute frame rates were meaningless — everything read 12 fps. The *relative* figure
      is sound because it was measured under identical load: classic 12.000 vs all effects
      11.999. The 144 fps acceptance criterion needs re-measuring on an idle machine.
- [x] Parallax starfield, 3 depth layers — `starfieldEffect` (on), `starfieldDensity` (45).
      Stars come from a fixed seed through a private generator, so the sky is identical every
      frame and every session and does not disturb the global `rand()` stream. Each layer
      scrolls at a fraction of the view (0.15 / 0.35 / 0.60), tiled on a 1024px grid.
      Verified view-linked rather than static: thrusting for 2.5s changed 2,849 pixels in a
      region of otherwise empty space.
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
| 2026-08-25 | 1 (cont.) | Removed autotools: 66 files deleted plus the parity CI job. Verified no build target was lost (the extra directories are EXTRA_DIST only), the install tree still diffs clean at 99 files, and a clean rebuild keeps the same 55-warning profile. `version.h` kept as a checked-in header to avoid re-encoding the authors' ISO-8859-1 names, with a CMake guard against version drift. | `phase1-remove-autotools` |
| 2026-08-25 | 1 | Wrote `docs/build-audit.md` (what autotools actually detects, plus four findings including a dead `HAVE_SDLIMAGE` spelling that silently disables `IMG_Load`). Added a CMake build reaching verified parity with autotools: same 5 binaries, same 55 warnings, smoke test passes, both build systems coexist. Added a GitHub Actions workflow; first run failed on three real CI-environment issues (missing X11 fonts, uninstalled data files, and an assertion that raced client stdout buffering), second run green. Install parity verified exact at 99 files. Autotools still in place, removal left as a separate reviewable change. | `phase1-cmake` |
| 2026-08-25 | 0 | Audited actual build state against the checklist. `./configure && make` clean: 0 errors, 55 warnings, all 5 binaries built. Server + both X11 and SDL clients verified against a local 4-robot game; 5-minute soak passed, so Phase 0 acceptance is met. Found the server exits when the last human leaves (`-noQuit` needed) and that audio is compiled out (no OpenAL headers). Wrote `BUILDING.md` and closed out Phase 0. No C source was touched this session — the compile fixes were already on `master`. | `phase0-baseline` (docs only; branched from `b7a6905`) |
