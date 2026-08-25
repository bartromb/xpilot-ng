# Build audit: what autotools actually does

Phase 1 input. This records what the existing autotools build detects, defines and
links, so the CMake port can be checked against it rather than guessed at.

Captured 25 Aug 2026 on the Phase 0 reference machine (Linux Mint 22.2 / Ubuntu 24.04
base, GCC 13.3). Values marked *(resolved)* are what `configure` actually produced here;
they are not portable constants.

## Targets

Two static convenience libraries and five executables. Nothing is a shared library.

| Target | Type | Dir | `.c` files |
|---|---|---|---|
| `libxpcommon.a` | static lib | `src/common` | 15 |
| `libxpclient.a` | static lib | `src/client` | 22 |
| `xpilot-ng-server` | executable | `src/server` | 50 |
| `xpilot-ng-x11` | executable | `src/client/x11` | 21 |
| `xpilot-ng-sdl` | executable | `src/client/sdl` | 21 |
| `xpilot-ng-replay` | executable | `src/replay` | 2 |
| `xpilot-ng-xp-mapedit` | executable | `src/mapedit` | 13 |

Link structure — every executable pulls in `libxpcommon.a`; only the two clients also
pull in `libxpclient.a`:

```
libxpcommon.a  <- server, x11, sdl, replay, mapedit
libxpclient.a  <- x11, sdl
```

Note `src/client/Makefile.am` puts `.` first in `SUBDIRS` specifically to force
`libxpclient.a` to build before the SDL client. CMake handles this ordering through
target dependencies, so the workaround does not need porting.

### Per-target link lines *(resolved)*

Empty substitutions are left in to show what autotools contributed nothing to.

| Target | Libraries |
|---|---|
| `xpilot-ng-server` | `libxpcommon.a` + `-lexpat -lz -lm` |
| `xpilot-ng-x11` | `libxpclient.a libxpcommon.a` + `-lSM -lICE -lX11` + `-lexpat -lz -lm` |
| `xpilot-ng-sdl` | `libxpclient.a libxpcommon.a` + `-lSDL -lGL -lGLU -lSDL_ttf -lSDL_image -lSM -lICE -lX11` + `-lexpat -lz -lm` |
| `xpilot-ng-replay` | `libxpcommon.a` + `-lSM -lICE -lX11` + `-lexpat -lz -lm` |
| `xpilot-ng-xp-mapedit` | `libxpcommon.a` + `-lSM -lICE -lX11` + `-lexpat -lz -lm` |

`X_LIBS`, `X_EXTENSIONS_LIB`, `X_EXTRA_LIBS`, `W32_LIBS` and `SOUND_LIBS` all resolve
to empty here. `LIBS` (`-lexpat -lz -lm`) is global and applied to every target,
including ones that arguably do not need it.

### Compile flags *(resolved)*

| Variable | Value |
|---|---|
| `CFLAGS` | `-g -O2` |
| `DEFS` | `-DHAVE_CONFIG_H` |
| `CPPFLAGS` | *(empty)* |
| `SDL_CFLAGS` | `-I/usr/include/SDL -D_GNU_SOURCE=1 -D_REENTRANT` |

Every target additionally gets `-DCONF_DATADIR=\"$(pkgdatadir)/\"`, i.e.
`/usr/local/share/xpilot-ng/` at the default prefix.

Include paths, by target:

- `src/common` — none beyond its own directory
- `src/server`, `src/mapedit`, `src/replay` — `src/common`
- `src/client` and both clients — `src/common`, `src/client`

## Generated files

`configure` generates these; CMake must reproduce them:

| File | From | Contents |
|---|---|---|
| `config.h` | `config.h.in` | 100 `#define`s, 20 `#undef`s |
| `src/common/version.h` | `version.h.in` | `TITLE`, `VERSION`, `AUTHORS`, `COPYRIGHT` |

`version.h` substitutes `@PACKAGE_STRING@`, `@VERSION@`, `@XP_AUTHORS@` and
`@XP_COPYRIGHT@`; the copyright date `1991-2005` is hardcoded in `configure.ac`.

## config.h — what actually matters

`configure` emits 100 defines, but most are `AC_CHECK_HEADERS` results the code never
consults. Cross-referencing the generated `config.h` against every `#ifdef`/`#if
defined` in `src/` gives **71 macros the source actually reads**:

- 62 `HAVE_*` header/function probes — one of which, `HAVE_CONFIG_H`, is not in
  `config.h` at all but comes from `-DHAVE_CONFIG_H` on the command line
- 9 feature and platform macros: `DBE`, `DEVELOPMENT`, `MBX`, `PLOCKSERVER`,
  `SELECT_SCHED`, `SOUND`, `STDC_HEADERS`, `TIME_WITH_SYS_TIME`, `_WINDOWS`

Macros defined by `configure` but **never read by any source file**: `REPLAY`,
`SDL_CLIENT`, `X11_CLIENT`, `XP_MAPEDIT`. These only drive automake conditionals, so in
CMake they should become build options that select targets — there is no need to put
them in the generated `config.h` at all.

Of those 71, one (`HAVE_CONFIG_H`) comes from the command line and one (`HAVE_SDLIMAGE`) is
never defined anywhere — see Findings — leaving **69 macros `config.h` is actually
responsible for**. The port does not need to replicate all 80 `HAVE_*` probes; reproducing
those 69 is sufficient and much easier to keep honest.

## Options and conditionals

`configure` flag → automake conditional → effect:

| Flag | Default | Conditional | Effect |
|---|---|---|---|
| `--disable-x11-client` | on | `COND_X11_CLIENT` | build `src/client/x11` |
| `--disable-sdl-client` | on | `COND_SDL_CLIENT` | build `src/client/sdl` |
| `--disable-replay` | on | `COND_REPLAY` | build `src/replay` |
| `--disable-xp-mapedit` | on | `COND_XP_MAPEDIT` | build `src/mapedit` |
| `--enable-sound` | **off** | `COND_SOUND` | adds `caudio.c oalaudio.c` to `libxpclient.a`, links `-lopenal -lalut`, installs `lib/sound` |
| `--enable-sdl-gameloop` | off | `COND_SDL_GAMELOOP` | `gameloop.c` instead of `gameloop_x.c` |
| *(implicit)* | — | `COND_CLIENT` | build `libxpclient.a` if either client is enabled |
| *(implicit)* | — | `COND_WINDOWS` | adds `win32hacks.c`, drops `-lX11` |

Also available, all off by default and all mapping to a single `config.h` define:
`--enable-dbe` (`DBE`), `--enable-mbx` (`MBX`), `--enable-plockserver` (`PLOCKSERVER`),
`--enable-development` (`DEVELOPMENT`), `--enable-select-sched` (`SELECT_SCHED`).

Only two conditionals change the **source list** rather than just flags —
`COND_SOUND` and `COND_SDL_GAMELOOP` (plus `COND_WINDOWS`, out of scope for a Linux
port). Everything else selects whole targets.

## Data files installed

Into `$(pkgdatadir)` = `$(prefix)/share/xpilot-ng/`:

| Source | Destination |
|---|---|
| `lib/{defaults,password,robots,shipshapes}.txt` | `share/xpilot-ng/` |
| `lib/maps/*.xp2`, `*.xpd` | `share/xpilot-ng/maps/` |
| `lib/fonts/` | `share/xpilot-ng/fonts/` |
| `lib/textures/` | `share/xpilot-ng/textures/` |
| `lib/sound/` | `share/xpilot-ng/sound/` *(only when `COND_SOUND`)* |

The binaries also run straight from the build tree without installing, which is how
the Phase 0 smoke test worked.

## Findings

Things the port should decide about deliberately rather than inherit by accident.

**`HAVE_SDLIMAGE` is dead code.** `configure` defines `HAVE_SDL_IMAGE` (with the
underscore), and `glwidgets.c`, `sdlmeta.c` and `xpclient_sdl.h` test that spelling. But
`SDL_console.c:719` and `DT_drawtext.c:78` test `HAVE_SDLIMAGE` — no underscore — which
nothing ever defines. Both sites therefore always take the `#else` branch and call
`SDL_LoadBMP` instead of `IMG_Load`, so console backgrounds and bitmap fonts are
restricted to BMP even though SDL_image is linked in. This is a pre-existing bug, not a
regression. The CMake port should reproduce current behaviour for parity, then fix the
spelling as a separate, reviewable commit.

**`-L/usr/X11R6/lib` is stale.** `GL_LIBS` resolves to `-lSDL -L/usr/X11R6/lib -lGL
-lGLU`. That path has not existed on Linux since the X.Org migration around 2005 and is
absent here. It is harmless — the linker ignores missing `-L` paths — but should not be
carried into CMake; use `find_package(OpenGL)` instead.

**`LIBS` is applied globally.** `-lexpat -lz -lm` goes on every link line. The server
and map editor genuinely use expat and zlib; whether `xpilot-ng-replay` does was not
verified. CMake should attach these per target, which will also reveal any target that
was only linking them by inheritance.

**SDL detection uses `sdl-config`, not pkg-config.** `configure` shells out to
`sdl-config`; the resolved `-I/usr/include/SDL` comes from there. On this machine
`sdl-config` belongs to `sdl12-compat` 1.2.68, an SDL2 shim. CMake should use
`find_package(SDL)`/pkg-config for `sdl12_compat`, and Phase 2 will replace this
path with SDL2 outright.

**The `AC_FUNC_*` legacy probes are entirely dead.** `configure` runs
`AC_FUNC_MEMCMP`, `AC_FUNC_STAT`, `AC_FUNC_SETVBUF_REVERSED`, `AC_FUNC_STRTOD` and
`AC_FUNC_SELECT_ARGTYPES`, guarding against pre-POSIX libc bugs no supported platform
has. Every macro they produce — including `SELECT_TYPE_ARG1`, `SELECT_TYPE_ARG234` and
`SELECT_TYPE_ARG5`, which look load-bearing — is read by **no source file in the tree**
(verified by grep across `src/`). Drop these probes rather than porting them; nothing
will notice.
