# Building XPilot NG

XPilot NG 4.7.3 still builds with its original autotools setup on a current
Linux system — no `autoreconf` and no source surgery beyond the compile fixes
already on `master`.

There are currently **two** build systems in the tree. CMake is the one to use;
autotools is kept working alongside it until CMake has proven itself in CI, at
which point Phase 1 of `ROADMAP.md` removes it.

## Verified environment

The instructions below were verified end to end on 25 Aug 2026:

| | |
|---|---|
| OS | Linux Mint 22.2 (Ubuntu 24.04 "noble" base) |
| Compiler | GCC 13.3.0 |
| Result | 5 binaries, 0 errors, 55 warnings |

Clang and GCC 14 have not been tried yet.

## Dependencies

```sh
sudo apt install build-essential \
    libx11-dev libsm-dev libice-dev \
    libgl-dev libglu1-mesa-dev \
    libsdl1.2-dev libsdl-ttf2.0-dev libsdl-image1.2-dev \
    libexpat1-dev zlib1g-dev
```

What each one is for:

| Package | Needed by |
|---|---|
| `libx11-dev`, `libsm-dev`, `libice-dev` | X11 client (`-lX11 -lSM -lICE`) |
| `libgl-dev`, `libglu1-mesa-dev` | SDL/OpenGL client (`-lGL -lGLU`) |
| `libsdl1.2-dev` | SDL client; provides `sdl-config` |
| `libsdl-ttf2.0-dev`, `libsdl-image1.2-dev` | SDL client fonts and textures |
| `libexpat1-dev` | XML map parsing (server *and* clients) |
| `zlib1g-dev` | map and recording compression |

Note that on Ubuntu 24.04 `libsdl1.2-dev` is **not** real SDL 1.2 — it is
`sdl12-compat` (version 1.2.68), a shim that implements the SDL 1.2 API on top
of SDL2. The client therefore already runs on SDL2 underneath, which is worth
knowing before starting the Phase 2 port.

Autotools (`autoconf`, `automake`, `libtool`) is **not** required. The tarball's
generated `configure` works as-is; you only need autotools if you change
`configure.ac` or `Makefile.am`.

### Optional: sound

Sound is opt-in and is **off** in the default build. To attempt it:

```sh
sudo apt install libopenal-dev libalut-dev
./configure --enable-sound
```

`freealut` (`libalut`) is effectively a dead library; replacing this whole path
with SDL2_mixer is Phase 3 of the roadmap. Be aware that `configure` treats
missing audio libraries as non-fatal: if you pass `--enable-sound` without
OpenAL and freealut present, it prints

```
*** Client sound disabled. Check that you have OpenAL installed.
```

and then continues with a silent build. Check for `#define SOUND 1` in the
generated `config.h` to confirm sound was actually enabled.

## Build (CMake — preferred)

```sh
cmake -B build -S .
cmake --build build -j"$(nproc)"
```

Binaries land in `build/bin/`. Useful options, all mirroring the old
`configure` flags:

| Option | Default | Effect |
|---|---|---|
| `-DXPILOT_X11_CLIENT=OFF` | ON | skip the X11 client |
| `-DXPILOT_SDL_CLIENT=OFF` | ON | skip the SDL/OpenGL client |
| `-DXPILOT_REPLAY=OFF` | ON | skip the replay tool |
| `-DXPILOT_MAPEDIT=OFF` | ON | skip the map editor |
| `-DXPILOT_SOUND=ON` | OFF | OpenAL sound (requires `libopenal-dev libalut-dev`) |
| `-DXPILOT_SDL_GAMELOOP=ON` | OFF | use the SDL game loop instead of the X11-optimised one |

Turning off every client also drops the X11 and SDL dependencies entirely, so a
server-only build needs just `build-essential libexpat1-dev zlib1g-dev`.

Unlike autotools, `-DXPILOT_SOUND=ON` **fails** if OpenAL or freealut is
missing rather than quietly building without sound.

## Build (autotools — legacy)

```sh
./configure
make -j"$(nproc)"
```

This produces five binaries, left in the source tree (no `make install`
required to run them):

| Binary | Purpose |
|---|---|
| `src/server/xpilot-ng-server` | game server |
| `src/client/x11/xpilot-ng-x11` | plain X11 client |
| `src/client/sdl/xpilot-ng-sdl` | SDL/OpenGL client |
| `src/replay/xpilot-ng-replay` | recording playback |
| `src/mapedit/xpilot-ng-xp-mapedit` | map editor |

The build currently emits 55 warnings and no errors. The bulk are
`-Wdiscarded-qualifiers` (25) and `-Wunused-result` (8), concentrated in
`forms.c` and `file.c`. A captured baseline is in `build-log-baseline.txt`.

### Useful configure flags

| Flag | Effect |
|---|---|
| `--disable-x11-client` | skip the X11 client |
| `--disable-sdl-client` | skip the SDL/OpenGL client |
| `--disable-replay` | skip the replay tool |
| `--disable-xp-mapedit` | skip the map editor |
| `--enable-sound` | attempt OpenAL sound (see above) |
| `--enable-sdl-gameloop` | use the SDL game loop instead of the X11-optimised one |
| `--enable-select-sched` | alternative server scheduling, aimed at Linux 2.6+ |

`./configure --help` lists the rest.

## Running a local game

Paths below are the autotools ones; for a CMake build substitute
`build/bin/xpilot-ng-server` and `build/bin/xpilot-ng-sdl`.

Start a server with robots:

```sh
./src/server/xpilot-ng-server -map lib/maps/dodgers-robots.xp2 \
    -maxRobots 4 -minRobots 4 -port 15000 -noQuit -idleRun &
```

Connect a client:

```sh
./src/client/sdl/xpilot-ng-sdl -join -name yourname -port 15000 localhost
# or
./src/client/x11/xpilot-ng-x11 -join -name yourname -port 15000 localhost
```

`-noQuit` and `-idleRun` matter more than they look — see below.

## Gotchas

**The server exits when the last human player leaves.** By default
`xpilot-ng-server` shuts down cleanly (exit code 0) the moment the last human
disconnects; robots alone do not keep it alive. If you then start a second
client it will sit there printing `Retrying localhost...` against a server that
no longer exists, which looks exactly like a broken client. Pass `-noQuit` (wait
for new players) and `-idleRun` (keep simulating while empty) for any server
that should outlive a single session.

**The host is a positional argument.** Use `-port 15000 localhost`. The
`localhost:15000` form is not parsed and fails with `Can't find the server`.

**Checking whether the server is alive.** Linux truncates process names to 15
characters, so the process shows up as `xpilot-ng-serve` — `pgrep -x
xpilot-ng-server` never matches. `pgrep -f xpilot-ng-server` is worse: it also
matches any enclosing `timeout ...` wrapper, which outlives the server, and the
shell command doing the check. Use `pgrep -x xpilot-ng-serve` or
`ss -ulnp | grep :15000`. For the same reason, kill the server by saved PID
rather than with `pkill -f`.

**Missing `~/.xpilotrc` is harmless.** Both clients print

```
ERROR: Xpilotrc_read: Failed to open file "/home/you/.xpilotrc"
```

on first run. It is logged as an error but is not fatal; the client proceeds
with defaults.

**Data files are not installed by default.** `configure` points the data
directory at `/usr/local/share/xpilot-ng/`. Running the binaries from the source
tree works because maps and textures are found under `lib/`; if you
`make install` to a prefix, keep the two consistent.
