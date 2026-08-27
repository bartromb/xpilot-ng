"""Turns toward the nearest visible ship and fires when roughly lined up.

Unlike the other two, this one perceives: it reads decoded frames and steers
from them. It is still simple on purpose -- a proportional turn and a firing
cone, no lead, no evasion -- because the point is to show the loop
(observe, decide, act), not to be good at the game.
"""

from __future__ import annotations

import math
import time

from ..client import Client
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

            # Pick the closest ship that is not us.
            target = None
            best = None
            for ship in frame.ships:
                dx, dy = ship.x - me.x, ship.y - me.y
                d2 = dx * dx + dy * dy
                if d2 == 0:
                    continue          # that is us
                if best is None or d2 < best:
                    best, target = d2, ship

            if target is None:
                # Nothing in view: cruise, so we do not sit still being shot.
                c.press(p.KEY_THRUST)
                c.send_keys()
                continue

            delta = _turn_delta(_bearing(target.x - me.x, target.y - me.y),
                                me.heading)

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
