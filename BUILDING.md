# Building XPilot NG

XPilot NG 4.7.3 builds cleanly on a current Linux system with no source
surgery beyond the compile fixes already on `master`.

The build system is CMake. The original autotools build was removed at the end
of Phase 1 (see `ROADMAP.md`) once CMake had reached verified parity; there is
no `./configure` any more.

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

Autotools (`autoconf`, `automake`, `libtool`) is **not** required and is no
longer used at all.

### Optional: sound

Sound is opt-in and is **off** in the default build. To attempt it:

```sh
sudo apt install libopenal-dev libalut-dev
cmake -B build -S . -DXPILOT_SOUND=ON
```

`freealut` (`libalut`) is effectively a dead library; replacing this whole path
with SDL2_mixer is Phase 3 of the roadmap. Unlike the old autotools build,
which downgraded missing audio libraries to a warning and silently produced a
mute binary, `-DXPILOT_SOUND=ON` fails outright if OpenAL or freealut is
missing.

## Build

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

## Running a local game

Start a server with robots:

```sh
./build/bin/xpilot-ng-server -map lib/maps/dodgers-robots.xp2 \
    -maxRobots 4 -minRobots 4 -port 15000 -noQuit -idleRun &
```

Connect a client:

```sh
./build/bin/xpilot-ng-sdl -join -name yourname -port 15000 localhost
# or
./build/bin/xpilot-ng-x11 -join -name yourname -port 15000 localhost
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
