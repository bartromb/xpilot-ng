# Tests and fuzz harnesses

## `fuzz_packet_scanf.c`

Fuzzes `Packet_scanf`, the parser every network handler funnels through — the
pre-authentication contact path and every `PKT_*` handler. A flaw there is a
flaw in all of them at once, which is why it is the first target. See the
attack-surface section of `docs/protocol.md`.

### With AFL++ (preferred)

```sh
afl-gcc -O1 -Isrc/common -Ibuild/generated -DHAVE_CONFIG_H \
    -DCONF_DATADIR='"/usr/local/share/xpilot-ng/"' \
    tests/fuzz_packet_scanf.c src/common/{net,socklib,error,portability,strlcpy,strdup,strcasecmp,xpmemory}.c \
    -o fuzz_packet_scanf -lm
afl-fuzz -i tests/fuzz_corpus -o findings -- ./fuzz_packet_scanf @@
```

### Without AFL++

The harness can generate its own input. This is dumb random fuzzing with no
coverage guidance, so it is much weaker than AFL++, but it needs nothing
installed:

```sh
gcc -O1 -fsanitize=undefined -Isrc/common -Ibuild/generated -DHAVE_CONFIG_H \
    -DCONF_DATADIR='"/usr/local/share/xpilot-ng/"' \
    tests/fuzz_packet_scanf.c src/common/{net,socklib,error,portability,strlcpy,strdup,strcasecmp,xpmemory}.c \
    -o fuzz_packet_scanf -lm
./fuzz_packet_scanf --selftest 200000
```

### A caveat about AddressSanitizer on this machine

ASan does not work on the development machine, and it is not the harness's
fault: a trivial `printf("hello")` compiled with `-fsanitize=address`
segfaults too. The cause is `/etc/ld.so.preload` injecting
`/usr/local/lib/AppProtection/libAppProtection.so` into every process, which
collides with ASan's shadow memory. UBSan is unaffected and is what found the
bugs recorded below. If you want ASan coverage, run it somewhere without that
preload — a container is easiest.

## What this has found so far

Three undefined-behaviour sites in `Packet_scanf`, all reachable from
attacker-controlled packet bytes, all fixed:

| Site | Format | Problem |
|---|---|---|
| `net.c:585` | `%d` | `sbuf->ptr[j++] << 24` — `char` is signed, so a byte ≥ 0x80 shifts a negative value |
| `net.c:660` | `%ld` | same |
| `net.c:606` | `%u` | masked but `(int)209 << 24` overflows `int` |

The tell was that the *following* bytes in each expression are masked with
`& 0xFF` and only the top byte is not — an inconsistency within one
statement rather than a uniform style.

Two more sites of the same shape (`%hd`, `%hu`, `%lu`) were fixed at the same
time; fuzzing had not happened to reach them.

These decode network integers, so the fix was checked for behaviour change as
well as for UB: a round-trip test over 34 edge cases — `INT_MIN`,
`0x80000000`, `0xD1000000` (the exact `209 << 24` case), and the negative
values UBSan reported — recovers every value bit-for-bit.

## `mapdata/`

Map data download and extraction against a hostile server.

A map names the URL of its texture package, so the URL — and the package behind
it — are chosen by whichever server a player joins. `serve.py` serves one honest
package behind the kind of redirect the real mirror uses, plus packages built
to break the client: a 1000-byte file name, `../` and `..\` traversal, a
decompression bomb, a redirect to `file://`, an error page, a lying
`Content-Length` and a truncated download. `fetch.c` calls the client's own
`Mapdata_setup()` without a window; `run.sh` runs every case and checks the
outcome and what was left on disk.

Build `fetch.c` with the sanitizers. Several of these cases were memory errors
before they were refusals, and only an instrumented build tells the two apart:

```sh
cc -g -O1 -fsanitize=address,undefined -DHAVE_CONFIG_H -DHAVE_LIBCURL \
   -DCONF_DATADIR='"/usr/share/xpilot-ng/"' \
   -Ibuild/generated -Isrc/common -Isrc/client \
   src/client/mapdata.c src/common/error.c tests/mapdata/fetch.c \
   $(pkg-config --cflags --libs libcurl zlib) -o mapdata-fetch
sh tests/mapdata/run.sh ./mapdata-fetch lib/maps/ndh.xpd
```

Run against the code from before the libcurl change, the suite fails eight of
its eleven cases, one of them with AddressSanitizer reporting the stack overflow
in the old extractor.

