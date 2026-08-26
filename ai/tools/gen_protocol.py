#!/usr/bin/env python3
"""Generate xpilot_bot/protocol.py from the C headers.

The bot has to agree with the server byte for byte, so these constants are
extracted from the headers rather than transcribed by hand. Re-run after any
change to keys.h, packet.h or pack.h:

    python3 ai/tools/gen_protocol.py

Run from the repository root.
"""

from __future__ import annotations

import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "ai" / "xpilot_bot" / "protocol.py"


def read(path: str) -> str:
    return io.open(ROOT / path, encoding="utf-8", errors="surrogateescape").read()


def enum_keys() -> list[str]:
    """keys_t members up to NUM_KEYS: their order is the keyboard bit order."""
    src = read("src/common/keys.h")
    body = re.search(r"typedef enum\s*\{(.*?)\}\s*keys_t", src, re.S).group(1)
    out = []
    for line in body.splitlines():
        t = line.strip()
        if t.startswith("NUM_KEYS"):
            break
        if t.startswith("KEY_"):
            out.append(t.split()[0].rstrip(","))
    return out


def defines(path: str, pattern: str) -> dict[str, int]:
    src = read(path)
    out = {}
    for m in re.finditer(
        r"^#define\s+(" + pattern + r")\s+(0x[0-9A-Fa-f]+|\d+)", src, re.M
    ):
        out[m.group(1)] = int(m.group(2), 0)
    return out


def main() -> int:
    keys = enum_keys()
    pkts = defines("src/common/packet.h", r"PKT_\w+")
    packs = defines("src/common/pack.h", r"\w+_pack")
    # Status bytes: SUCCESS plus the E_* family. SUCCESS does not share the
    # E_ prefix, which is easy to miss and produces an AttributeError at the
    # worst moment -- during the join handshake.
    codes = defines("src/common/pack.h", r"SUCCESS|E_\w+")

    if not keys or not pkts or not packs or "SUCCESS" not in codes:
        print("error: extraction produced an incomplete set", file=sys.stderr)
        return 1

    L = [
        '"""XPilot NG protocol constants.',
        "",
        "GENERATED FILE -- do not edit by hand.",
        "Produced from src/common/{keys,packet,pack}.h by ai/tools/gen_protocol.py,",
        "so the bot cannot drift from the server it has to talk to.",
        '"""',
        "",
        "MAGIC_WORD = 0xF4ED",
        "",
        "",
        "def version_to_magic(version: int) -> int:",
        '    """VERSION2MAGIC from pack.h."""',
        "    return ((version & 0xFFFF) << 16) | MAGIC_WORD",
        "",
        "",
        "def magic_to_version(magic: int) -> int:",
        "    return (magic >> 16) & 0xFFFF",
        "",
        "",
        "KEYBOARD_SIZE = 9  # bytes; one bit per protocol key",
        "MAX_CHARS = 80",
        "MSG_LEN = 256",
        "SERVER_PORT = 15345",
        "",
        "# --- keys_t in enum order: the value is the bit index in the",
        "#     keyboard vector, which is how every action is sent ---",
    ]
    L += [f"{k} = {i}" for i, k in enumerate(keys)]
    L += ["", f"NUM_KEYS = {len(keys)}", "",
          "# --- contact-phase packet types (pack.h) ---"]
    L += [f"{k} = 0x{v:02X}" for k, v in sorted(packs.items(), key=lambda kv: kv[1])]
    L += ["", "# --- status / error codes (pack.h) ---"]
    L += [f"{k} = 0x{v:02X}" for k, v in sorted(codes.items(), key=lambda kv: kv[1])]
    L += ["", "# --- game-phase packet types (packet.h) ---"]
    L += [f"{k} = {v}" for k, v in sorted(pkts.items(), key=lambda kv: kv[1])]

    OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(
        f"wrote {OUT.relative_to(ROOT)}: {len(keys)} keys, {len(pkts)} PKT_*, "
        f"{len(packs)} *_pack, {len(codes)} status codes"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
