"""Turns toward the nearest visible ship and fires when roughly lined up.

Unlike the other two, this one perceives: it reads decoded frames and steers
from them. It is still simple on purpose -- a proportional turn and a firing
cone, no lead, no evasion -- because the point is to show the loop
(observe, decide, act), not to be good at the game.

It does have to handle one thing that is not optional: the world wraps. Fly
off the right edge and you come back on the left (confirmed by watching a
ship go from y=3144 to y=0 in a single frame), so subtracting coordinates
points the turn the long way round whenever our view straddles the seam.
The server culls to the client's view, so every visible ship is nearby --
but the view is 1024 wide on a 3150-wide map, so it straddles the seam
roughly a third of the time, and measurement puts the naive nearest-ship
answer wrong 40% of the time. See `wrapped_delta`.

Honesty about what that buys *here*: it is not visible in this bot's aim.
Alternating wrapped and naive runs of 3,000 frames each gave 10.9 vs 14.8
heading units in one round and 12.5 vs 10.4 in the next -- the run-to-run
variance is larger than the effect. A bot that re-decides every frame
recovers from a bad bearing on the next one. It matters much more for the
learning agent in `env.py`, which is trained on that bearing as a reward.
"""

from __future__ import annotations

import math
import time

from ..client import Client
from ..frames import wrapped_delta
from .. import protocol as p

# Headings are 0..127 rather than degrees.
HEADING_STEPS = 128
FIRE_CONE = 8          # steps either side of dead ahead


def _bearing(dx: float, dy: float) -> float:
    """Heading, in XPilot's 0..128 units, of the vector (dx, dy)."""
    return (math.atan2(dy, dx) / (2 * math.pi)) * HEADING_STEPS % HEADING_STEPS


def _turn_delta(want: float, have: float) -> float:
    """Signed shortest turn from `have` to `want`, in heading units."""
    d = (want - have + HEADING_STEPS / 2) % HEADING_STEPS - HEADING_STEPS / 2
    return d


def run(host: str = "localhost", port: int = 15345, seconds: float = 60.0) -> None:
    with Client(host=host, port=port, nick="hunter", user="hunter") as c:
        start = time.time()
        while time.time() - start < seconds:
            frame = c.poll()
            if frame is None or frame.self_ is None:
                continue

            me = frame.self_
            c.release_all()

            # The world wraps on most maps, so "closest" and "which way" both
            # have to go the short way round the seam. The map size is on the
            # reliable stream; before it arrives, wrapped_delta is told zero
            # and falls back to plain subtraction.
            setup = c.reliable.board.setup
            w = setup.width if setup else 0
            h = setup.height if setup else 0

            # Pick the closest ship that is not us.
            target = None
            best = None
            target_delta = (0, 0)
            for ship in frame.ships:
                dx, dy = wrapped_delta(w, h, me.x, me.y, ship.x, ship.y)
                d2 = dx * dx + dy * dy
                if d2 == 0:
                    continue          # that is us
                if best is None or d2 < best:
                    best, target, target_delta = d2, ship, (dx, dy)

            if target is None:
                # Nothing in view: cruise, so we do not sit still being shot.
                c.press(p.KEY_THRUST)
                c.send_keys()
                continue

            delta = _turn_delta(_bearing(*target_delta), me.heading)

            if delta > 1:
                c.press(p.KEY_TURN_LEFT)
            elif delta < -1:
                c.press(p.KEY_TURN_RIGHT)

            if abs(delta) <= FIRE_CONE:
                c.press(p.KEY_FIRE_SHOT)

            # Close the distance, but not while turning hard, or we sail past.
            if abs(delta) < HEADING_STEPS / 8:
                c.press(p.KEY_THRUST)

            c.send_keys()


if __name__ == "__main__":
    run()
