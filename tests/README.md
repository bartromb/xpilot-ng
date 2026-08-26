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
