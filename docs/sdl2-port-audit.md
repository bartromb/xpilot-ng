# SDL2 port audit (Phase 2)

Input for the SDL 1.2 → SDL2 port. Captured 26 Aug 2026 against SDL2 2.30.0.

Method: every `SDL_*` identifier in `src/client/sdl/` was extracted and checked against the
installed SDL2 headers, rather than relying on recollection of what SDL2 dropped. Project-local
identifiers that merely start with `SDL_` were then filtered out by looking for their definitions
in the tree.

## Scope

| Measure | Count |
|---|---|
| Distinct `SDL_*` symbols referenced | 99 |
| Total references | 711 |
| Symbols absent from SDL2 headers | 39, of which **26 are genuinely removed API** |
| Call sites needing change | **58**, across 11 files |
| Lines in `src/client/sdl/` | 11,471 |
| …of which vendored third-party | 8,787 (77%) |

The 13 false positives were project-local names that happen to start with `SDL_` — most of them
in `scrap.c`, which declares its own `SDL_Display` and `SDL_Window_internal` statics.

## The starting position is better than the roadmap assumes

`ROADMAP.md` frames Phase 2 as "SDL 1.2 → SDL2". In fact the client already *runs* on SDL2:
`libsdl1.2-dev` on Ubuntu 24.04 is `sdl12-compat` 1.2.68, a shim implementing the 1.2 API on top
of SDL2. Nothing here is running real SDL 1.2.

So this port does not buy "works on SDL2" — it already does. What it buys is **access to APIs the
1.2 shim cannot expose**: high-DPI, proper window events, `SDL_TEXTINPUT`, GameController, and
multi-monitor. Those are the actual Phase 2 and Phase 4 goals. Worth being explicit about, because
it changes the cost/benefit of touching shim-compatible code that works fine as-is.

## Where the 58 call sites are

| File | Sites | Kind |
|---|---|---|
| `sdlinit.c` | 17 | project — video setup |
| `sdlevent.c` | 10 | project — event loop |
| `SDL_console.c` | 8 | vendored |
| `text.c` | 6 | project |
| `sdlmeta.c` | 4 | project |
| `SDL_gfxPrimitives.c` | 4 | vendored |
| `sdlpaint.c` | 3 | project |
| `scrap.c` | 2 | vendored |
| `gameloop_x.c` | 2 | project |
| `radar.c` | 1 | project |
| `DT_drawtext.c` | 1 | vendored |

43 sites in project code, 15 in vendored code.

## API mapping

| SDL 1.2 | SDL2 replacement | Sites |
|---|---|---|
| `SDL_SetVideoMode` | `SDL_CreateWindow` + `SDL_GL_CreateContext` | 4 |
| `SDL_GetVideoInfo` / `SDL_VideoInfo` | `SDL_GetCurrentDisplayMode` | 2 |
| `SDL_ListModes` | `SDL_GetNumDisplayModes` / `SDL_GetDisplayMode` | 1 |
| `SDL_GL_SwapBuffers` | `SDL_GL_SwapWindow(win)` | 2 |
| `SDL_WM_SetCaption` | `SDL_SetWindowTitle` | 1 |
| `SDL_WM_ToggleFullScreen` | `SDL_SetWindowFullscreen` | 1 |
| `SDL_WM_GrabInput` / `SDL_GRAB_*` | `SDL_SetWindowGrab` | 4 |
| `SDL_GetWMInfo` | none needed — both sites are dead or deleted (see below) | 1 |
| `SDL_DisplayFormat` | `SDL_ConvertSurfaceFormat` | 6 |
| `SDL_SetAlpha` | `SDL_SetSurfaceAlphaMod` + `SDL_SetSurfaceBlendMode` | 5 |
| `SDL_EnableUNICODE` + `keysym.unicode` | `SDL_StartTextInput` + `SDL_TEXTINPUT` | 3 + 2 |
| `SDL_VIDEORESIZE` / `SDL_VIDEOEXPOSE` | `SDL_WINDOWEVENT` subtypes | 2 |
| `SDL_SELECTION` | gone; SDL2 has clipboard API | 1 |
| Surface flags: `SDL_SRCALPHA`, `SDL_HWSURFACE`, `SDL_HWPALETTE`, `SDL_HWACCEL`, `SDL_RLEACCELOK` | mostly meaningless in SDL2; drop | 14 |
| Window flags: `SDL_OPENGL`, `SDL_FULLSCREEN`, `SDL_RESIZABLE` | `SDL_WINDOW_*` equivalents | 11 |

Note the hardware-surface flags in `sdlinit.c` are chosen from `videoInfo->hw_available` and
`blit_hw`, concepts SDL2 removed outright. That whole block collapses to nothing — it is not
a port so much as a deletion.

## The vendored code is where the real win is

77% of `src/client/sdl/` is third-party code bundled in the 1.2 era. It is worth measuring how
much of it is actually used before porting any of it.

### `SDL_gfxPrimitives` — 6,764 lines serving 3 call sites

`SDL_gfxPrimitives.c` (3,683 lines) plus `SDL_gfxPrimitives_font.h` (3,081 lines) are included by
exactly two files and used for exactly three calls:

```
sdlpaint.c:371   lineRGBA
sdlpaint.c:508   lineRGBA
radar.c:226      filledPolygonRGBA
```

`libsdl2-gfx-dev` is packaged on Ubuntu (1.0.4) and provides `lineRGBA` and `filledPolygonRGBA`
under **the same names and signatures**. Replacing the vendored copy with the packaged library is
close to a drop-in: change the include, add the dependency, delete 6,764 lines. The three call
sites should not need to change at all.

### `scrap.c` — 651 lines, obsoleted entirely

A clipboard shim that reaches through `SDL_GetWMInfo` to raw X11 (and Win32) to implement
copy/paste, because SDL 1.2 had no clipboard API. SDL2 has `SDL_GetClipboardText` and
`SDL_SetClipboardText`. Four functions are used (`init_scrap`, `lost_scrap`, `put_scrap`,
`get_scrap`); all become one-liners or disappear. Delete the file.

This one also removes the client's only direct X11 dependency in the SDL path, which matters for
the Wayland goal.

### `SDL_console.c` + `DT_drawtext.c` — 1,372 lines, genuinely used

The in-game console. 14 `CON_*` entry points are used by `console.c` and `glwidgets.c`, and
`DT_drawtext.c` exists only to serve it. This is the one vendored component that has to be ported
rather than dropped. Two things to handle:

- `keysym.unicode` at `SDL_console.c:1067` and `:1070` is the text-entry path, and is the reason
  `SDL_EnableUNICODE` is called. This becomes `SDL_StartTextInput` and an `SDL_TEXTINPUT` handler.
- The `HAVE_SDLIMAGE` misspelling in this file was already fixed in `9ab8bc8`, so the image
  loading path is `IMG_Load` now and needs no further attention during the port.
- While in here, fix the three `strncat(dst, src, strlen(src))` sites recorded in
  `docs/warnings-debt.md`. They are in this file and the bound cannot protect the destination.

Net: of 8,787 vendored lines, roughly **7,400 can be deleted** and about 1,400 ported.

## What does not need to change

- **Keybindings are stored by name, not keycode.** `sdlkeys.c` maps names through an `sdlkeys[]`
  table, and `String_to_xp_keysym` resolves a name to `SDLK_*`. SDLK values are renumbered in
  SDL2, but since nothing persists the numbers, existing `~/.xpilotrc` keybindings survive. This
  was the main compatibility risk and it is not one.
- **The game's own event dispatch.** `sdlevent.c` reads `evt->key.keysym.sym` and casts to
  `xp_keysym_t`; the field exists in SDL2 with the same meaning.
- **Surface, Rect, MapRGBA, BlitSurface, LockSurface, CreateRGBSurface, FillRect** — 60 of the 99
  symbols are unchanged in SDL2. The HUD/score/radar surface code largely carries over.
- `SDLKey` is renamed `SDL_Keycode`; a one-line typedef keeps `sdlkeys.c` untouched if wanted.

## Suggested sequence

1. **Delete `scrap.c`**, switch to SDL2 clipboard. Smallest, self-contained, removes an X11
   dependency.
2. **Swap vendored `SDL_gfxPrimitives` for `libsdl2-gfx`.** Large deletion, three call sites,
   no behaviour change expected.
3. **Port `sdlinit.c`** — window + GL context creation, and delete the hardware-flag block.
   This is the change that unlocks high-DPI and proper resize.
4. **Port `sdlevent.c`** — window events and grab.
5. **Port `SDL_console.c`** — text input, plus the `strncat` fixes.
6. **Surfaces and blitting** — `SDL_DisplayFormat` and `SDL_SetAlpha` sites in `text.c`,
   `sdlmeta.c`, `sdlpaint.c`.
7. Build flags: swap `sdl12_compat`/`SDL_ttf`/`SDL_image` for `sdl2`/`SDL2_ttf`/`SDL2_image`
   in `CMakeLists.txt`, and update `BUILDING.md` and CI dependencies.

Steps 1 and 2 are pure deletion and can land before any behavioural port begins.

## Risks

- **No way to A/B against the old renderer once the port starts.** Worth keeping the X11 client
  building (Phase 2's last checklist item offers exactly that choice) as a visual reference.
- **CI cannot see rendering.** The headless smoke test proves the client connects and creates a GL
  context; it cannot prove the game looks right. Rendering regressions need a human or
  screenshots.
- **Rendering correctness is the whole risk surface.** Everything else here is mechanical.

## Resolved while auditing

The other `SDL_GetWMInfo` call, at `sdlevent.c:60`, looked like it might share `scrap.c`'s raw-X11
dependency and block its removal. It does not: it sits inside `#ifdef HAVE_XF86MISC`, and
`HAVE_XF86MISC` is never defined — it is `#undef` in the old autotools `config.h` and an
unset `#cmakedefine` now. The block is dead code, along with the `Disable_emulate3buttons` call
it guards. So `scrap.c` can go without touching it, and step 1 is unblocked.

That leaves `SDL_GetWMInfo` with no live callers in the SDL client at all once `scrap.c` is
deleted, so `SDL_GetWindowWMInfo` never needs to be wired up.
