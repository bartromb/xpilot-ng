"""The LLM strategy layer, and the classical controller under it.

The property that matters most here is not that the model gives good advice.
It is that nothing it does -- being slow, being unreachable, answering
"Attack!", answering with prose, raising -- can stop the ship from flying.
Most of these tests are about that.
"""

import json
import math

import pytest

from xpilot_bot import protocol as p
from xpilot_bot.strategy import (BackgroundStrategist, Decision, LLMStrategist,
                                 ScriptedStrategist, Strategist,
                                 _first_json_object)
from xpilot_bot.tactics import TACTICS, Contact, Situation, plan_keys


# ------------------------------------------------------ the controller


def sit(**kw):
    return Situation(**kw)


def test_every_tactic_produces_keys_that_exist():
    s = sit(enemies=[Contact(dist=300, bearing=0.5)],
            shots=[Contact(dist=100, bearing=-1.0)])
    for tactic in TACTICS:
        for key in plan_keys(s, tactic):
            assert 0 <= key < 72, f"{tactic} produced key {key}"


def test_hunting_turns_toward_and_fires_when_lined_up():
    lined_up = sit(enemies=[Contact(dist=200, bearing=0.0)])
    assert p.KEY_FIRE_SHOT in plan_keys(lined_up, "hunt")

    to_port = sit(enemies=[Contact(dist=200, bearing=1.0)])
    keys = plan_keys(to_port, "hunt")
    assert p.KEY_TURN_LEFT in keys, "port is a left turn; headings rise CCW"
    assert p.KEY_FIRE_SHOT not in keys, "no shooting at nothing"


def test_evading_turns_away_not_toward():
    s = sit(shots=[Contact(dist=100, bearing=0.2)])
    keys = plan_keys(s, "evade")
    assert p.KEY_TURN_RIGHT in keys, "threat to port means turn starboard"
    assert p.KEY_THRUST in keys
    assert p.KEY_SHIELD in keys, "shields when it is this close"


def test_evading_a_distant_threat_does_not_burn_shields():
    s = sit(shots=[Contact(dist=900, bearing=0.2)])
    assert p.KEY_SHIELD not in plan_keys(s, "evade")


def test_sniping_backs_off_when_crowded_rather_than_closing():
    close = sit(enemies=[Contact(dist=100, bearing=0.0)])
    keys = plan_keys(close, "snipe")
    assert p.KEY_THRUST in keys
    assert p.KEY_FIRE_SHOT not in keys, "too close to be sniping"


def test_regrouping_never_shoots():
    s = sit(enemies=[Contact(dist=300, bearing=3.0)])
    assert p.KEY_FIRE_SHOT not in plan_keys(s, "regroup")
    assert p.KEY_SHIELD not in plan_keys(s, "regroup")


def test_a_dead_ship_presses_nothing():
    s = sit(alive=False, enemies=[Contact(dist=10, bearing=0.0)])
    assert plan_keys(s, "hunt") == ()


def test_an_unknown_tactic_patrols_rather_than_raising():
    """This runs every frame. A strategist saying something strange must not
    be able to crash the ship."""
    s = sit(speed=0.0)
    assert plan_keys(s, "obliterate everything") == (p.KEY_THRUST,)
    assert plan_keys(s, "") == (p.KEY_THRUST,)


# ------------------------------------------------------ decisions


@pytest.mark.parametrize("raw,expected", [
    ("hunt", "hunt"),
    ("  Hunt  ", "hunt"),
    ('"snipe"', "snipe"),
    ("evade.", "evade"),
    ("regrouping", "regroup"),
    ("I would patrol here", "patrol"),
])
def test_near_miss_tactics_are_salvaged(raw, expected):
    assert Decision(raw).validated().tactic == expected


def test_an_unsalvageable_tactic_becomes_patrol_and_says_so():
    d = Decision("launch the nukes", source="llm").validated()
    assert d.tactic == "patrol"
    assert "rejected" in d.source, "the fallback must be visible in the log"


def test_json_is_found_inside_prose_and_code_fences():
    assert _first_json_object('```json\n{"tactic": "hunt"}\n```') == {"tactic": "hunt"}
    assert _first_json_object('Sure! {"tactic": "evade", "say": "bye"} ok')["say"] == "bye"
    assert _first_json_object('{"a": {"b": 1}} trailing')["a"] == {"b": 1}


def test_a_reply_with_no_json_is_an_error_not_a_guess():
    with pytest.raises(ValueError):
        _first_json_object("I think you should attack them")


# ------------------------------------------------------ the rules


def test_the_scripted_strategist_evades_incoming_fire_first():
    """Fire about to land outranks a target worth shooting at."""
    s = sit(fuel=500, shots=[Contact(dist=40, bearing=0.0)],
            enemies=[Contact(dist=200, bearing=0.0)])
    assert ScriptedStrategist().decide(s).tactic == "evade"


def test_the_scripted_strategist_breaks_off_when_out_of_fuel():
    s = sit(fuel=40, enemies=[Contact(dist=200, bearing=0.0)])
    assert ScriptedStrategist().decide(s).tactic == "regroup"


def test_the_scripted_strategist_patrols_with_nothing_in_view():
    assert ScriptedStrategist().decide(sit()).tactic == "patrol"


def test_a_normal_spawn_is_not_treated_as_an_emergency():
    """A ship spawns with about 300 fuel against a tank capacity of 2600 --
    11% -- so any rule phrased as a fraction of capacity fires immediately
    and never stops. It did, and the bot ran away for a whole match."""
    spawn = sit(fuel=300, fuel_max=2600,
                enemies=[Contact(dist=200, bearing=0.0)])
    assert ScriptedStrategist().decide(spawn).tactic == "hunt"


# ------------------------------------------------------ the model


def test_no_api_key_means_rules_not_an_exception():
    llm = LLMStrategist(api_key="")
    assert not llm.available()
    assert llm.decide(sit()).source == "scripted"


def test_an_unreachable_endpoint_falls_back_and_is_counted():
    llm = LLMStrategist(api_key="x", timeout=0.2,
                        endpoint="http://127.0.0.1:9/none")
    d = llm.decide(sit(enemies=[Contact(dist=100, bearing=0.0)]))
    assert d.tactic in TACTICS
    assert d.source == "scripted"
    assert llm.failures == 1, "a silent fallback is worse than a counted one"


def test_the_situation_report_is_readable_before_it_is_sent():
    s = sit(fuel=300, speed=12, score=30, kills=2, deaths=1,
            enemies=[Contact(dist=180, bearing=-math.pi / 2)])
    text = LLMStrategist._describe(s)
    assert "fuel 300" in text
    assert "2 kills" in text
    assert "180 away at 3 o'clock" in text, "starboard is 3 o'clock"


# ------------------------------------------------------ the thread


class _Slow(Strategist):
    interval = 0.01

    def __init__(self, delay=0.2, tactic="hunt"):
        self.delay, self.tactic, self.calls = delay, tactic, 0

    def decide(self, situation):
        self.calls += 1
        import time
        time.sleep(self.delay)
        return Decision(self.tactic, source="slow")


def test_the_control_loop_never_waits_for_a_slow_strategist():
    import time
    bg = BackgroundStrategist(_Slow(delay=0.3), initial="patrol").start()
    try:
        bg.observe(sit())
        started = time.time()
        for _ in range(200):
            assert bg.current.tactic in TACTICS
        assert time.time() - started < 0.1, "reading a decision must be free"
    finally:
        bg.stop()


def test_a_decision_eventually_arrives_and_is_taken_up():
    import time
    strategist = _Slow(delay=0.01, tactic="snipe")
    bg = BackgroundStrategist(strategist, initial="patrol").start()
    try:
        bg.observe(sit())
        deadline = time.time() + 3.0
        while time.time() < deadline and bg.current.tactic != "snipe":
            time.sleep(0.02)
        assert bg.current.tactic == "snipe"
        assert bg.updates >= 1
    finally:
        bg.stop()


class _Exploding(Strategist):
    interval = 0.01

    def decide(self, situation):
        raise RuntimeError("model on fire")


def test_a_strategist_that_raises_keeps_the_last_tactic():
    import time
    bg = BackgroundStrategist(_Exploding(), initial="hunt").start()
    try:
        time.sleep(0.2)
        assert bg.current.tactic == "hunt", "the ship keeps flying"
    finally:
        bg.stop()


def test_a_distant_shot_does_not_call_off_the_attack():
    """In a firefight there is almost always some shot within a couple of
    hundred pixels. Breaking off for those means never attacking: measured,
    0 kills against 18 deaths, versus 7 against 19 with a tighter trigger."""
    from xpilot_bot.tactics import EVADE_RANGE
    far = sit(fuel=500, shots=[Contact(dist=EVADE_RANGE * 2, bearing=0.0)],
              enemies=[Contact(dist=200, bearing=0.0)])
    assert ScriptedStrategist().decide(far).tactic == "hunt"

    onto_us = sit(fuel=500, shots=[Contact(dist=EVADE_RANGE / 2, bearing=0.0)],
                  enemies=[Contact(dist=200, bearing=0.0)])
    assert ScriptedStrategist().decide(onto_us).tactic == "evade"
