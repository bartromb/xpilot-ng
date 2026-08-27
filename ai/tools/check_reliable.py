#!/usr/bin/env python3
"""Assert the reliable sub-stream really decodes against a live server.

The unit tests cover reassembly with synthetic bytes. This covers the thing
they cannot: that the bytes a real server sends are the bytes we think they
are. Every mistake in this area found so far -- a mis-sized PKT_PLAYER, a
segment hidden inside a frame packet -- was invisible to the tests and
obvious here within a few seconds.

Run against a server with robots on it:

    python ai/tools/check_reliable.py --port 15401 --seconds 45

It fails loudly, because a silent reliable stream looks exactly like a quiet
game.
"""

from __future__ import annotations

import argparse
import sys
import time

from xpilot_bot import protocol as p
from xpilot_bot.client import Client


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=15401)
    ap.add_argument("--seconds", type=float, default=45.0)
    ap.add_argument("--nick", default="Checker")
    args = ap.parse_args(argv)

    c = Client(host=args.host, port=args.port, nick=args.nick, fps=60)
    c.connect()
    board = c.reliable.board

    # Hold a turn for the whole run. A ship that never sends PKT_TURNSPEED
    # cannot turn, and nothing anywhere says so -- the keys are accepted and
    # the heading just never changes. Checking it here costs nothing.
    c.press(p.KEY_TURN_RIGHT)
    c.send_keys()

    ship_ids = set()
    headings = set()
    end = time.time() + args.seconds
    while time.time() < end:
        frame = c.poll()
        if frame is not None:
            ship_ids.update(s.id for s in frame.ships)
            if frame.self_ is not None:
                headings.add(frame.self_.heading)
    turnspeed = c.frame.self_.turnspeed if c.frame and c.frame.self_ else 0
    power = c.frame.self_.power if c.frame and c.frame.self_ else 0
    c.release_all()
    c.send_keys()
    c.close()

    problems = []

    if len(headings) < 8:
        problems.append(
            f"held turn-right for {args.seconds:.0f}s and saw only "
            f"{len(headings)} distinct heading(s): the ship cannot turn. "
            f"turnspeed={turnspeed}, power={power} -- see send_ship_controls")

    # A truncated frame is no longer merely a gap in perception. Finding a
    # piggybacked reliable segment means walking the datagram packet by
    # packet, so an unknown type part-way through stops the walk -- and any
    # segment behind it goes unacknowledged, which is how the server comes to
    # drop a client that looks perfectly healthy.
    if c.status.truncated_frames:
        problems.append(
            f"{c.status.truncated_frames} frames could not be walked to the "
            f"end, so any reliable segment inside them was missed")

    if c.reliable.desynced:
        problems.append(
            f"stream desynchronised at packet type {c.reliable.desynced_at} "
            f"after {c.reliable.offset} bytes")
    if board.unknown:
        problems.append(f"undecoded packet types: {board.unknown}")
    if board.setup is None:
        problems.append("never decoded the setup blob")
    if board.own_id is None:
        problems.append("never identified which player we are")

    # Ships appear in frames; players appear on the reliable stream. A ship
    # with no matching player means reliable data was missed -- which is what
    # a client that only reads datagram byte zero looks like from here.
    missing = ship_ids - set(board.players)
    if missing:
        problems.append(
            f"ships {sorted(missing)} were visible in frames but never "
            f"announced on the reliable stream (known players: "
            f"{sorted(board.players)})")

    print(f"stream:   {c.reliable.offset} bytes, desynced={c.reliable.desynced}")
    print(f"setup:    {board.setup.name if board.setup else None!r} "
          f"{board.setup.width if board.setup else '?'}x"
          f"{board.setup.height if board.setup else '?'}")
    print(f"players:  {{{', '.join(f'{i}: {pl.nick!r}' for i, pl in sorted(board.players.items()))}}}")
    print(f"messages: {len(board.messages)}")
    print(f"handling: turnspeed={turnspeed} power={power}, "
          f"{len(headings)} distinct headings while turning")
    print(f"counts:   { {k: v for k, v in sorted(board.counts.items())} }")

    if problems:
        print("\nFAILED:", file=sys.stderr)
        for line in problems:
            print(f"  - {line}", file=sys.stderr)
        return 1

    print("\nok: reliable stream decoded cleanly")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
