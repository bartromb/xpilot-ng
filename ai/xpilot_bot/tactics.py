"""A classical controller, and the situation summary that drives it.

The roadmap's stretch goal is an LLM as a *high-level strategy layer* on top
of a classical controller, explicitly never for frame-level control, because
the latency is unsuitable. This module is the classical controller: it turns
one word -- a tactic -- into keys to hold, every frame, with no thinking
involved. Deciding which word is `strategy.py`'s job, and it may take a
second or two over it.

The split is what makes the idea workable. At 255 frames per second a frame
is four milliseconds; nothing that talks to a network API can be in that
loop. But "should I be attacking or running away right now" changes on the
order of seconds, and that is a question a language model can usefully answer
while the controller keeps flying.

Everything here is a pure function of a `Situation`, so it can be tested
without a server.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import protocol as p

#: The tactics a strategist may choose. Anything else is rejected rather
#: than guessed at -- see strategy.Decision.
TACTICS = ("hunt", "evade", "snipe", "regroup", "patrol")

#: Fire when the target is within this many radians of dead ahead.
FIRE_CONE = 0.22

#: Below this, turning is close enough; keeps the ship from oscillating.
AIM_DEADBAND = 0.05

#: Fuel thresholds, in game units. Calibrated against a spawn of about 300.
LOW_FUEL = 80.0
CAUTIOUS_FUEL = 180.0

#: Ranges in world pixels.
#: How close a shot has to be before breaking off is worth the lost attack.
#: See ScriptedStrategist for why this is much smaller than it first was.
EVADE_RANGE = 90.0

CLOSE_RANGE = 250.0
SNIPE_RANGE = 600.0
DANGER_RANGE = 180.0


@dataclass
class Contact:
    """Something worth reacting to, relative to us."""

    dist: float
    #: Signed radians from our nose. Positive is to port, matching XPilot's
    #: headings, which increase counter-clockwise.
    bearing: float


@dataclass
class Situation:
    """Everything the controller and the strategist are allowed to know.

    Deliberately small. It is also what gets serialised into a prompt, and a
    prompt that carries the whole world is both slow and worse at deciding.
    """

    alive: bool = True
    #: Fuel in the game's own units, not a fraction of the tank.
    #:
    #: `fuel_max` is tank *capacity*, which you raise by collecting tanks, so
    #: a ship can be perfectly healthy at 11% of it -- that is what you start
    #: with on dodgers-robots. A "below 15% of max" rule therefore fires from
    #: the moment you spawn and never stops, which is exactly what the first
    #: version of this did: it broke off and ran for an entire match.
    fuel: float = 500.0
    fuel_max: float = 2600.0
    speed: float = 0.0
    enemies: list = field(default_factory=list)   # of Contact, nearest first
    shots: list = field(default_factory=list)     # of Contact, nearest first
    score: float = 0.0
    kills: int = 0
    deaths: int = 0
    #: What we are doing now, so a strategist can be told what it is changing.
    tactic: str = "patrol"

    @property
    def nearest_enemy(self) -> Contact | None:
        return self.enemies[0] if self.enemies else None

    @property
    def nearest_shot(self) -> Contact | None:
        return self.shots[0] if self.shots else None


def _turn_toward(bearing: float) -> tuple[int, ...]:
    """Keys to swing the nose onto `bearing`."""
    if bearing > AIM_DEADBAND:
        return (p.KEY_TURN_LEFT,)
    if bearing < -AIM_DEADBAND:
        return (p.KEY_TURN_RIGHT,)
    return ()


def _turn_away(bearing: float) -> tuple[int, ...]:
    """Keys to swing the nose to the opposite of `bearing`."""
    opposite = bearing - math.copysign(math.pi, bearing)
    return _turn_toward(opposite)


def plan_keys(situation: Situation, tactic: str) -> tuple[int, ...]:
    """Keys to hold this frame, given a situation and a tactic.

    An unknown tactic falls back to patrolling rather than raising: this is
    called every frame, and a strategist -- particularly one backed by a
    language model -- should never be able to crash the ship by saying
    something unexpected.
    """
    if not situation.alive:
        return ()

    if tactic == "hunt":
        return _hunt(situation)
    if tactic == "evade":
        return _evade(situation)
    if tactic == "snipe":
        return _snipe(situation)
    if tactic == "regroup":
        return _regroup(situation)
    return _patrol(situation)


def _hunt(s: Situation) -> tuple[int, ...]:
    """Close on the nearest enemy and shoot it."""
    target = s.nearest_enemy
    if target is None:
        return _patrol(s)

    keys = list(_turn_toward(target.bearing))
    # Only burn fuel closing the distance while roughly pointed the right
    # way; thrusting sideways just adds drift to correct later.
    if target.dist > CLOSE_RANGE and abs(target.bearing) < 0.8:
        keys.append(p.KEY_THRUST)
    if abs(target.bearing) < FIRE_CONE:
        keys.append(p.KEY_FIRE_SHOT)
    return tuple(keys)


def _evade(s: Situation) -> tuple[int, ...]:
    """Get away from whatever is closest, shot or ship."""
    threat = s.nearest_shot or s.nearest_enemy
    if threat is None:
        return _patrol(s)

    keys = list(_turn_away(threat.bearing))
    keys.append(p.KEY_THRUST)
    # Shields are expensive, so they come out only when something is about to
    # arrive rather than as a habit.
    if threat.dist < DANGER_RANGE:
        keys.append(p.KEY_SHIELD)
    return tuple(keys)


def _snipe(s: Situation) -> tuple[int, ...]:
    """Hold range and fire only on a good line.

    The point is fuel: hunting closes and thrusts constantly, which is how a
    bot ends up out of fuel in the middle of a fight.
    """
    target = s.nearest_enemy
    if target is None:
        return _patrol(s)

    if target.dist < CLOSE_RANGE:
        # Too close to snipe. Back off first; turning toward and away in the
        # same frame just cancels out.
        return tuple(_turn_away(target.bearing)) + (p.KEY_THRUST,)

    keys = list(_turn_toward(target.bearing))
    if target.dist > SNIPE_RANGE and abs(target.bearing) < 0.5:
        keys.append(p.KEY_THRUST)
    # A tighter cone than hunting: the whole point is not wasting shots.
    if abs(target.bearing) < FIRE_CONE * 0.6:
        keys.append(p.KEY_FIRE_SHOT)
    return tuple(keys)


def _regroup(s: Situation) -> tuple[int, ...]:
    """Break off. No firing, no shields, just distance and quiet."""
    threat = s.nearest_enemy or s.nearest_shot
    if threat is None:
        return ()
    keys = list(_turn_away(threat.bearing))
    if abs(threat.bearing) > math.pi - 0.9:
        # Pointing away already, so the thrust actually takes us somewhere.
        keys.append(p.KEY_THRUST)
    return tuple(keys)


def _patrol(s: Situation) -> tuple[int, ...]:
    """Nothing to react to: keep moving so we are not a stationary target."""
    if s.speed < 4.0:
        return (p.KEY_THRUST,)
    return ()
