# XPilot NG — revived

A modernization of [XPilot NG](http://xpilot.org) 4.7.3, the multiplayer space
war game whose last release was in 2010. The goal is a codebase that builds and
runs cleanly on current Linux while staying compatible with thirty years of
maps, recordings and the original network protocol.

This is a fork of the archival mirror `kekyo/xpilot-ng`. Upstream has seen no
development since 2010 and is kept here only as a provenance link.

> The original project README is preserved as [`README`](README) — it carries
> the authors' names and copyright, and nothing here replaces their work.

## State of play

| Phase | What | Status |
|---|---|---|
| 0 | Builds at all on modern Linux | **Done** |
| 1 | autotools → CMake | **Done** — autotools removed |
| 2 | SDL 1.2 → SDL2 | **Done** — Wayland unverified |
| 3 | Audio: OpenAL/freealut → SDL2_mixer | **Done** — not yet judged by ear |
| 4 | Quality of life | **Done** — keybind defaults left alone deliberately |
| 4b | Graphics modernization | **Done** to the stretch line |
| 5 | Network & hosting | **Done** — including a self-hostable metaserver |
| 6a | Python bot SDK | **Done** — both packet streams decoded |
| 6b | Gymnasium RL environment | **Done** — accelerated and parallel |
| 6c | Learned agents | **Done** — PPO beats random; robots still won't fight |

Full detail, including everything deliberately *not* done and why, is in
[`ROADMAP.md`](ROADMAP.md).

## Quick start

```sh
sudo apt install build-essential cmake libx11-dev libsm-dev libice-dev \
    libgl-dev libglu1-mesa-dev libsdl2-dev libsdl2-ttf-dev libsdl2-image-dev \
    libexpat1-dev zlib1g-dev

cmake -B build -S .
cmake --build build -j"$(nproc)"

# a server with four robots
./build/bin/xpilot-ng-server -map lib/maps/blood-music.xp2 \
    -maxRobots 4 -minRobots 4 -port 15345 -noQuit -idleRun &

# and a client
./build/bin/xpilot-ng-sdl -join -name you -port 15345 localhost
```

`-noQuit -idleRun` are not optional decoration: without them the server exits
the moment the last human disconnects. [`BUILDING.md`](BUILDING.md) covers that
and the other traps.

## What changed

62 commits since the 4.7.3 import; 185 files, +17,600 / −52,800 lines. The
deletions are most of the story — a lot of this was removing things rather than
adding them.

**Build.** autotools replaced by CMake and then deleted outright: `configure`,
`configure.ac`, 27 `Makefile.am`, the aux scripts. Install output was diffed
against the old build to prove parity at 99 files. A `.deb` builds via CPack.
GitHub Actions builds, installs, and smoke-tests the server, both clients, the
sound path and a Python bot on every push.

**Client.** Ported to SDL2 and verified by A/B screenshot against the pre-port
build — identical rendering, no new warnings. `scrap.c`, 651 lines of raw-X11
clipboard shim, deleted in favour of SDL2's clipboard.

**Interface.** A `uiScale` option that auto-detects from display DPI, because
SDL2 on X11 reports a scale of 1.0 no matter how dense the panel is — so the
HiDPI problem people actually have is a font-scaling problem, not a drawable
one. XDG config directories with migration. Gamepad support. In-client key
rebinding through console commands.

**Graphics.** Additive glow, a parallax starfield, and particle trails — each
individually switchable at runtime, with a `classicRender` switch that restores
the original look. Classic mode was measured, not asserted: it differs from the
pre-effects build by fewer pixels than that build differs from *itself* between
runs.

**Audio.** OpenAL and the long-dead freealut replaced by SDL2_mixer. CI asserts
that nothing links freealut any more.

**Network.** The protocol is documented and audited for NAT. The dead
metaservers have a [replacement](metaserver/README.md) — dependency-free, and
speaking the original protocol so unmodified clients and servers can use it.
`-metaServerHost` on both ends means you can actually point at one; the
addresses used to be compiled in.

**Bots.** [`ai/`](ai/README.md) is a dependency-free Python client that speaks
the original protocol, so bots play against unmodified servers seeing only what
a human's client sees. **Both** of the game's packet streams are decoded: the
frame stream into world state — own ship, other ships, shots, items — and the
reliable sub-stream into players, messages and scores. The second one matters
more than it sounds, because nothing about a game's *outcome* is on the frame
stream at all; decoding it is what made kills and scores measurable.

On top of that sits a Gymnasium environment that runs faster than realtime and
in parallel, PPO curriculum training, and a benchmark that compares any policy
against acting at random — including on the server's own score, which is
computed by the game and owes nothing to the reward function.

## Bugs found and fixed

Several of these had been in the code for decades:

- **Undefined behaviour in the packet parser**, found by fuzzing. `char` is
  signed, so `ptr[j++] << 24` shifts a negative value for any byte ≥ 0x80 —
  reachable pre-authentication. The fix was verified not to change wire
  decoding at all. ([`tests/`](tests/README.md))
- **The reliable sub-stream hides inside frame packets.** Before play it
  arrives as datagrams of its own; once frames start the server appends it to
  the *end of a frame update*, so a client checking only the first byte goes
  deaf exactly when the game begins. Nothing errors — scores and kills simply
  never arrive, and the server quietly drops the connection with a retransmit
  timeout that reads like a network fault.
- **Dying does not stop the frame stream.** The C client's own comment
  suggests a frame without `PKT_SELF` means the player is dead, so that is
  where death detection naturally goes. Measured against a live server, an
  idle bot died ten times in ninety seconds without a single frame missing
  its `PKT_SELF`. Together with the bug above, this is why "the robots never
  kill the bot" was believed for so long. They kill it constantly; nobody was
  listening.
- **`PKT_PLAYER` is mis-sized by the obvious reading of the protocol.** It
  carries *two* ship-shape strings, not one, and the reliable stream is
  undelimited — so reading one string turns everything after it into garbage.
  Both findings are in [`docs/protocol.md`](docs/protocol.md).
- **`Console_print` crashed on any format argument**, passing a `va_list` to a
  variadic function. Every existing caller passed a bare string, so it had
  never fired.
- **`strncat` bounded by the source length** in three places, making it exactly
  equivalent to `strcat`. One overflows a 128-byte buffer with the game's own
  prompt.
- **`HAVE_SDLIMAGE` was misspelled**, so `IMG_Load` was never compiled in and
  console fonts were silently BMP-only.
- **A startup race** where the client built its OpenGL context inside the
  server's login timeout — invisible on hardware, fatal under software
  rendering.

## Documentation

| | |
|---|---|
| [`ROADMAP.md`](ROADMAP.md) | plan, status, and what is deliberately undone |
| [`BUILDING.md`](BUILDING.md) | dependencies, options, and the traps |
| [`docs/protocol.md`](docs/protocol.md) | wire protocol and NAT audit |
| [`docs/build-audit.md`](docs/build-audit.md) | what autotools did, for the CMake port |
| [`docs/sdl2-port-audit.md`](docs/sdl2-port-audit.md) | the SDL 1.2 → SDL2 surface |
| [`docs/warnings-debt.md`](docs/warnings-debt.md) | the 52 remaining warnings, ranked |
| [`ai/README.md`](ai/README.md) | the Python bot SDK |
| [`metaserver/README.md`](metaserver/README.md) | the self-hosted metaserver |
| [`packaging/`](packaging/) | systemd units and Dockerfile |

## Known limits

Stated plainly, because they decide what is safe to rely on:

- **Wayland is untested.** The default game loop needs an X11 video driver and
  says so; native Wayland needs `-DXPILOT_SDL_GAMELOOP=ON` verified.
- **Audio has never been listened to.** It initialises, loads samples and feeds
  a stereo stream to PipeWire; whether it *sounds* right is unverified.
- **Positional audio is not implementable** as the roadmap describes. The audio
  packet carries a sound index and a volume, and no position.
- **The 144 fps target is unmeasured**, because the reference machine was under
  heavy unrelated load whenever it was tried.
- **Bots perceive, but the example bot is not good.** Frame decoding is
  complete; the `hunter` example aims better than chance and no more.
- **Death detection has never fired in a real game.** It works on synthetic
  frames, but the built-in robots did not kill the bot in thousands of steps
  and self-destruct did not either, so the live path is unproven.

## Licence

GPLv2, as the original. See [`COPYING`](COPYING).
