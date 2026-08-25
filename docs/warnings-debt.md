# Legacy warning debt

The standing instructions in `ROADMAP.md` say new code compiles clean under `-Wall
-Wextra` and legacy warnings get tracked here and reduced opportunistically. This is
the tracking.

Baseline: 55 warnings, 0 errors, from a clean CMake build with the project's default
flags (`-g -O2`, no explicit `-Wall -Wextra`) on GCC 13.3. Captured 25 Aug 2026; the
raw log is `build-log-baseline.txt`. The count has been identical across the autotools
and CMake builds, which is one of the parity signals recorded in `docs/build-audit.md`.

Note this is the *default* flag set. Turning on `-Wall -Wextra` will surface
considerably more; that is a deliberate future step, not a regression.

## By category

| Count | Category | Risk |
|---|---|---|
| 25 | `-Wdiscarded-qualifiers` | low |
| 18 | `-Wformat` family | low, except the `size_t` cases |
| 8 | `-Wunused-result` | low to moderate |
| 3 | `-Wstringop-overflow=` | **worth a real look** |
| 1 | `-Wpointer-to-int-cast` | low (ugly, not broken) |

## By file

Two files in the map editor account for over half the total:

| Count | File |
|---|---|
| 20 | `src/mapedit/forms.c` |
| 11 | `src/mapedit/file.c` |
| 3 | `src/client/clientcommand.c` |
| 3 | `src/client/sdl/SDL_console.c` |
| 2 | `src/replay/xp-replay.c` |
| 2 | `src/mapedit/main.c` |
| 2 | `src/server/teamcup.c` |
| 2 | `src/client/x11/xpaint.c` |
| 1 each | `help.c`, `mapdata.c`, `talkmacros.c`, `messages.c`, `srecord.c`, `suibotdef.c`, `server.c`, `sdlpaint.c`, `guimap.c`, `guiobjects.c` |

The concentration is convenient: fixing `forms.c` and `file.c` alone would cut the
count by 56%, and both are in the map editor, which is the least gameplay-sensitive
part of the tree. That makes them the natural first target under the "do not "clean
up" physics/gameplay constants" rule — there is no gameplay tuning to disturb.

## The ones that are not just noise

### `strncat` bounded by the source length — `SDL_console.c` 599, 1026, 1033

```c
strcpy(Topmost->VCommand, Topmost->Prompt);
strncat(Topmost->VCommand, &Topmost->Command[Topmost->Offset],
        strlen(&Topmost->Command[Topmost->Offset]));
```

The third argument to `strncat` is supposed to bound how much is written into the
destination. Passing `strlen(src)` makes it exactly equivalent to `strcat` — it cannot
protect anything. `VCommand` is `CON_CHARS_PER_LINE + 1` = 128 bytes, and both the
prompt and the command can be long, so prompt + command can exceed the buffer.

Whether this is reachable in practice depends on how long a prompt the console can be
given; that was not chased down. It should be, and this is the kind of thing the Phase 5
security pass is for. Fix by bounding on the destination's remaining capacity, e.g.
`sizeof(dst) - strlen(dst) - 1`, or by using `snprintf` into the buffer outright.

### `%d` against `size_t` — a few of the format warnings

Three of the 18 format warnings are real type mismatches rather than style, passing a
`size_t` where `%d` is expected. On 64-bit that is an 8-byte argument read as 4 bytes.
In practice these are all in diagnostic output paths, so the consequence is a wrong
number in a message rather than corruption, but they are trivially fixable with `%zu`.

### Ignored `fgets` return values — 8 sites

`-Wunused-result` on `fgets` and friends. Mostly in file-parsing paths where a short
read or EOF is treated as if it succeeded. Low risk on well-formed input, which is what
these paths have always been given; worth tightening whenever those parsers are touched
anyway.

## Explicitly not worth fixing

`src/mapedit/file.c:190`:

```c
if (strlen(prefs[n].charvar) != (int) NULL)
```

This is the lone `-Wpointer-to-int-cast`. `(int) NULL` is zero, so the condition means
"if the string is non-empty" and behaves correctly. It is bad style rather than a bug.
Left alone for now: changing it has no behavioural benefit, and the file has 11 other
warnings that should be fixed in one pass rather than piecemeal.

## Suggested order

1. `src/client/sdl/SDL_console.c` — the `strncat` sites, because they are the only ones
   with a plausible memory-safety story.
2. The three `size_t`/`%d` mismatches — one-line fixes.
3. `src/mapedit/forms.c` and `src/mapedit/file.c` — bulk of the count, lowest blast
   radius, no gameplay code involved.
4. Everything else, opportunistically, when the surrounding code is being touched for
   another reason.

Do not attempt a tree-wide warning sweep as a standalone change. The value is in
fixing warnings in code you are already modifying, where you can actually test the
result.
