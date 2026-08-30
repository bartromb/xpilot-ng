# XPilot NG — revived

A modernization of [XPilot NG](http://xpilot.org) 4.7.3, the multiplayer space
war game whose last release was in 2010. The goal is a codebase that builds and
runs cleanly on current Linux while staying compatible with thirty years of
maps, recordings and the original network protocol.

This is a fork of the archival mirror `kekyo/xpilot-ng`. Upstream has seen no
development since 2010 and is kept here only as a provenance link.

> The original project README is preserved as [`README`](README) — it carries
> the authors' names and copyright, and nothing here replaces their work.

## Download

Ready-to-run builds for all four targets are on the
**[Releases page](https://github.com/bartromb/xpilot-ng/releases/latest)**.

| Platform | Installer | Or unpack it yourself |
|---|---|---|
| Windows (x86-64) | `*-setup-x86_64.exe` | `*-windows-x86_64.zip` |
| macOS (Apple Silicon) | `*-macos-arm64.dmg` | `*-macos-arm64.tar.gz` |
| macOS (Intel) | `*-macos-x86_64.dmg` | `*-macos-x86_64.tar.gz` |
| Linux (Debian/Ubuntu, x86-64) | `xpilot-ng_*_amd64.deb` | — |

The Windows installer adds Start Menu shortcuts and an entry in Add/Remove
Programs. The `.dmg` holds an `XPilot NG.app` to drag to Applications. On
Linux: `sudo apt install ./xpilot-ng_*_amd64.deb`.

The zip and both tarballs are self-contained — every library ships alongside
the binaries, and the game finds its data wherever you put it, so there is
nothing to install first. On macOS use the `.tar.gz` as it is; repacking it as
a zip drops the executable bit.

Each release names what was actually verified and what was not. If you would
rather build from source, see [`BUILDING.md`](BUILDING.md).

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
| 6c | Learned agents | PPO trains and benchmarks; ahead of random on the server's own score |
| — | Windows and macOS | **Done** — server and SDL client, verified running in CI |
| — | Installers | **Done** — Windows setup and macOS `.dmg`, both run from an installed copy |

Full detail, including everything deliberately *not* done and why, is in
[`ROADMAP.md`](ROADMAP.md).

## Platforms

Linux is the reference platform and builds everything. Windows and macOS
build the **server** and the **SDL client**; the X11 client, replay tool and
map editor are Xlib programs and are not built there.

| | Linux | Windows | macOS |
|---|---|---|---|
| server | ✅ | ✅ | ✅ |
| SDL client | ✅ | ✅ | ✅ |
| X11 client, replay, map editor | ✅ | — | — |

Both are built by CI on real `windows-latest` and `macos-latest` runners, and
each job starts the server and checks it is listening. That check was not
ceremony: the Windows server built and linked perfectly while being incapable
of running for more than a few seconds, and only the runtime check caught it.
Every CI run attaches the same builds as artifacts, and releases publish them
as the downloads above. Both are made self-contained: the Windows one carries its mingw DLLs, the macOS one
has its Homebrew dylibs bundled and its load commands rewritten to
`@executable_path`. Each is checked for completeness before upload, because
the first versions of both shipped broken — the Windows build without
`libexpat-1.dll`, the macOS one pointing at `/opt/homebrew` — while every CI
job reported success.

That kind of check has a blind spot worth knowing about. Homebrew's `sdl2` is
sdl2-compat, which loads SDL3 with `dlopen` rather than linking it, so no load
command names it: `dylibbundler` did not bundle it, the "nothing points at
Homebrew" check did not miss it, and a full Mach-O scan of the published
`.dmg` called the app self-contained. It was not — without SDL3 the client
raised a modal alert from inside dyld and hung before `main()`. Nothing static
catches a `dlopen`; only running the thing did. CI now installs the app to
`/Applications` and requires it to join a game.

macOS is published for both architectures — `xpilot-ng-macos-arm64` for
Apple Silicon and `xpilot-ng-macos-x86_64` for Intel. Separate builds rather
than one universal binary, because Homebrew installs for the host
architecture only.

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

**Interface.** Smooth zoom on `+` and `-` (rebindable, animated, tunable via
`zoomSmoothing`). 4.7.3 had two fixed zoom *settings* and a key to swap
between them, but shipped that key unbound — so zoom could not be changed
mid-game at all. A `uiScale` option that auto-detects from display DPI, because
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
- **A client that never sends `PKT_TURNSPEED` has a ship that cannot turn.**
  `MIN_PLAYER_TURNSPEED` is 0.0 and players start at the minimum, so the
  turn keys are accepted, acknowledged, and do nothing — no error anywhere.
  Engine power behaves the same way, sitting at 5.0 instead of 55.0. Easy to
  mistake for bad flying.
- **The Windows server could never have run**, in any version of this tree.
  Three faults in one function: its timer installed a callback that exists
  nowhere in the source, the tick consumer never invoked the frame handler,
  and the scheduler had no loop — one pass and it fell through to shutdown.
  It builds, links, loads the map, prints "Server runs at 50 frames per
  second", and exits. Nothing but running it would have found this.
- **A joined ship ignores the controls for ~5 seconds.** Keyboard packets are
  accepted and acknowledged in every frame the whole time; the ship simply
  does not move. Re-sending does not help — the server skips any key update
  whose change counter it has already seen, so only a real press or release
  counts.
- **The world wraps, and the protocol never says so.** Most maps set
  `edgeWrap="yes"`, so subtracting two positions returns the long way round
  once they are more than half a map apart. Measured on a live game, that
  made 40% of "which opponent is nearest" answers wrong and put the average
  bearing out by 81°. The map size needed to correct it exists only in the
  setup blob at the head of the reliable stream.
- **Shots are not sent as coordinates.** `PKT_FASTSHOT`'s type byte is an
  index into a grid of 256-pixel tiles over the player's view, not a colour.
  Read it as a colour and every shot in the game piles into one corner of
  the map.
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
- **The `.deb` installed a game that could not find its own files.** It was
  built with the default `/usr/local` prefix, baking that path into the
  binaries, while CPack laid the package out under `/usr`. It looked fine on
  any machine that had also been `cmake --install`ed by hand, because the
  binaries then read *that* copy — which is exactly how the first two releases
  were "verified".
- **An installed copy found no data unless it was started from its own
  folder.** Windows and macOS compile a relative data path, so a Start Menu
  shortcut, a Finder launch or a shell anywhere else came up with no maps,
  textures, fonts or sounds. The macOS archives had it worse: they pointed at
  `/usr/local/share/xpilot-ng/` while shipping their data beside the binary.
  Startup now anchors the working directory to the executable.
- **The macOS app could never start.** Homebrew's `sdl2` is sdl2-compat, a shim
  that loads SDL3 with `dlopen` — so no load command names SDL3, `dylibbundler`
  never bundled it, and the shim's library initialiser raised a *modal alert
  from inside dyld*, waiting forever for a click. Silent, because the error
  went to a dialog rather than stderr. Three separate self-containment checks
  passed the bundle; none of them can see a `dlopen`.
- **`longjmp` out of the system resolver.** Both name lookups bounded
  `gethostbyname()` with `alarm()` and jumped out of the signal handler,
  unwinding through the resolver while it held its own locks. Undefined
  behaviour that needs a machine with slow DNS to show itself — it crashed the
  macOS server, and had been in the tree for years.
- **The SDL client drew nothing where a wall texture was missing.** Maps flag a
  polygon style as textured and then name a bitmap they never declare —
  `blood-music.xp2`, shipped with the game, does it on all 32 of its walls. The
  X11 client falls back to the style's colour; the SDL client left texturing
  enabled with nothing bound, so walls filled black and you flew into a map
  that looked empty. The radar draws walls by another path and kept showing
  them, which made it look like a collision bug rather than a drawing one.
- **A map download shortened the texture search path.** `strtok` was run
  directly over the path list every later texture lookup walks, so the first
  call truncated it to one entry — dropping the directory the map's own
  bitmaps had just been extracted into.
- **Sound was never built on Linux.** `XPILOT_SOUND` defaulted off and only the
  Windows and macOS CI jobs turned it on, so the packaged Linux build had
  neither the audio code nor the samples — their install rule is gated on the
  same option. The option now follows the library: sound is on when
  SDL2_mixer is installed. Confirmed by recording the audio device, not by
  ear: 41% of full scale while firing, against a silent baseline.
- **The Windows client killed its own connection.** It quit about a second
  after entering a game. Winsock reports through `WSAGetLastError()`, not
  `errno`, and its codes are different numbers: the code stored
  `WSAEWOULDBLOCK` (10035) into `errno` and compared it against `EWOULDBLOCK`
  (140) and `EAGAIN` (11), so a non-blocking read with no data yet could never
  be recognised as such. Every idle poll looked like a dead socket.
- **Windows builds could not report their own errors.** Every `error()`,
  `warn()` and `fatal()` funnelled into a function whose MessageBox was
  commented out and whose only other output expands to nothing outside debug
  builds. A Windows client could quit for a carefully worded reason and leave
  an empty log.
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

- **Nobody has run any of this on a Mac they own.** CI does start the macOS app
  from `/Applications` on both architectures and require it to join a game, so
  the path is exercised on real hardware — but no person has double-clicked it
  in the Finder.
- **The Windows client has only ever been run under Wine.** Everything works
  there — the installer, a Start Menu launch from outside the install folder,
  joining a game, sound, and a clean uninstall — but the Windows *server* is
  all CI exercises on real Windows.
- **Wayland is untested.** The default game loop needs an X11 video driver and
  says so; native Wayland needs `-DXPILOT_SDL_GAMELOOP=ON` verified.
- **Audio has never been listened to.** It demonstrably reaches the device on
  both the Linux and Windows builds — measured at about 41% of full scale while
  firing, against a silent baseline recorded with the client stopped — but
  whether it *sounds* right is unverified.
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
