# xpilot_bot

A headless Python client for XPilot NG. It speaks the original wire protocol,
so bots play against **unmodified servers** — nothing is patched into the game
to support them, and a bot sees only what a human player's client is sent.

No dependencies. Python 3.9+.

## Getting a bot flying

Start a server (from a built checkout):

```sh
./build/bin/xpilot-ng-server -map lib/maps/blood-music.xp2 \
    -maxRobots 2 -minRobots 2 -port 15345 -noQuit -idleRun &
```

`-noQuit -idleRun` matter: without them the server exits the moment the last
human leaves, and a bot-only server will not stay up.

Install and run:

```sh
pip install ./ai
xpilot-bot-wanderer
```

That is a bot flying in arcs on your server. To watch it, connect a real
client to the same server.

## Writing your own

```python
from xpilot_bot import Client, protocol as p

with Client(host="localhost", port=15345, nick="mybot") as c:
    for _ in range(600):
        c.release_all()
        c.press(p.KEY_THRUST)
        c.press(p.KEY_TURN_LEFT)
        c.press(p.KEY_FIRE_SHOT)
        c.send_keys()     # nothing happens until you send
        c.poll()          # read a datagram; also keeps the connection healthy
```

Two things to know:

- **Actions are held, not pulsed.** `press` sets a key down and it stays down
  until `release`. That mirrors the protocol, which sends a bitmap of held
  keys rather than events.
- **You must call `poll()` regularly.** It acknowledges the server's reliable
  stream. A client that never acknowledges gets dropped.

Every key in `keys.h` is available as `protocol.KEY_*` — `KEY_THRUST`,
`KEY_FIRE_SHOT`, `KEY_TURN_LEFT`, `KEY_SHIELD`, `KEY_FIRE_MISSILE` and 67
others.

## What this does and does not do

**Does:** the full join handshake, the keyboard vector so a bot can take any
action a human can, reliable-stream acknowledgement, and **frame decoding** —
`poll()` returns a `Frame` with your own ship's position, velocity, heading
and fuel, plus the other ships, shots, items, balls and mines in view.

**Does not:** interpret every packet type. Everything the server sends during
play is sized correctly, so decoding stays in sync, but only the types listed
above are turned into objects. `Frame.truncated` tells you when decoding
stopped early, and `last_raw` gives you the bytes.

That distinction matters more than it sounds. Packets are concatenated with no
length prefix, so an unknown type cannot be skipped — it desynchronises
everything after it. A frame that decodes at all decodes correctly.

## Perceiving

```python
frame = c.poll()
if frame and frame.self_:
    me = frame.self_
    print(me.x, me.y, me.heading, me.fuel)
    for ship in frame.ships:        # other players, in world coordinates
        print(ship.id, ship.x, ship.y, ship.heading, ship.shield)
```

Headings are **0..127, not degrees**, and increase counter-clockwise from the
+X axis, matching `atan2(dy, dx)`. That was verified rather than assumed: when
thrusting in a straight line, `atan2(vy, vx)` in those units equals the
reported heading exactly.

**You must tell the server how much to send you.** The client does this during
the handshake (`view_width`/`view_height`, default 1024x768). Without it the
server culls everything and you see only your own ship — which looks exactly
like an empty map, and is a memorable way to lose an hour.

## The handshake, and why it is fiddly

Worth knowing if you extend this, because each step below was discovered by
having the server hang up:

1. **Contact** on UDP 15345 with `CONTACT_pack`.
2. **Ask to join** with `ENTER_QUEUE_pack`. The reply carries a *different*
   port — the game does not run on 15345.
3. **Verify** on that second port with `PKT_VERIFY`.
4. **Drain setup.** The server pushes the map down the reliable stream and
   stays in `CONN_SETUP` until the client has acknowledged all of it. Send
   anything else here — a keyboard packet, say — and the server logs "unknown
   packet type" and destroys the connection.
5. **Request play** with `PKT_PLAY`, and wait for the server to start sending
   frames (`PKT_START`). Do not probe readiness by sending input: while still
   in setup that is precisely the packet that gets you disconnected, so the
   probe destroys what it measures.
6. **Send `PKT_DISPLAY`** once playing, to declare the view size. The server
   has separate packet tables per connection state and this one is only in the
   playing table, so sending it earlier is another disconnect.

`docs/protocol.md` in the repository root has the wire formats.

## Keeping in step with the C

`xpilot_bot/protocol.py` is generated from `src/common/{keys,packet,pack}.h`:

```sh
python3 ai/tools/gen_protocol.py
```

Constants are extracted rather than transcribed so the bot cannot drift from
the server it has to talk to. Re-run it after touching those headers.

## Reinforcement learning

```sh
pip install "./ai[rl]"
```

```python
from xpilot_bot.env import XPilotEnv, ServerProcess

with ServerProcess(port=15345, robots=2, fps=200) as srv:
    env = XPilotEnv(port=15345, fps=200, server=srv)
    obs, info = env.reset()
    for _ in range(1000):
        obs, reward, terminated, truncated, info = env.step(env.action_space.sample())
        if terminated or truncated:
            obs, info = env.reset()
    env.close()
```

**Observation** (26 floats): fuel, own velocity, heading as `(cos, sin)`, a
damage flag, then the four nearest ships as relative position, distance,
bearing error, and a presence flag. The presence flag is not padding for its
own sake — without it, an empty slot of zeros is indistinguishable from a ship
at exactly our position. Heading is `(cos, sin)` rather than a number because
127 and 0 are adjacent headings but distant numbers.

**Actions** (11): combinations of thrust, turn, fire and shield. XPilot keys
are *held*, not tapped, so an action is the set of keys held for that step.

**Reward** is deliberately plain — alive, fuel, facing the enemy. Shaping
belongs in the training curriculum, not baked into the environment where every
experiment would silently inherit it.

### Faster than realtime

Raise the frame rate on both ends. Raising only the server does nothing: it
sends at whatever rate the client asked for.

```python
ServerProcess(port=15345, fps=200)     # server runs at 200
XPilotEnv(port=15345, fps=200)         # and the client asks for 200
```

Measured 4x realtime at 200 fps. 255 is the ceiling, because the request is a
single byte.

### Parallel environments

XPilot has no notion of separate matches inside one server, so N environments
means N servers, each on its own port:

```python
from xpilot_bot.env import make_parallel
envs, _ = make_parallel(4, base_port=15400, fps=200)
```

Measured 800 steps/sec across 4 environments.

### Two honest limits

**It is not seedable.** `gymnasium.utils.env_checker.check_env` fails on
`check_step_determinism`, and correctly: this wraps a live server with its own
robots, so the same seed cannot reproduce a game. Every other applicable check
passes — observation and action spaces, reset return type and options, space
limits, and the passive reset/step checkers.

**Death detection is by absence.** The protocol has no "you died" packet;
what it has is a frame with no own-ship state, which `Receive_self` in the C
notes means "not actively playing: damaged, dead, paused or game over". A run
of `death_frames` such frames ends the episode. The mechanism is unit-tested
against synthetic frames (`ai/tests/test_death.py`); it has **not** been seen
to fire against a live server, because provoking a death on demand proved
unreliable -- holding self-destruct for thirty seconds produced none, and the
built-in robots never killed the bot in several thousand steps.

## Training an agent

```sh
pip install "./ai[rl]" stable-baselines3
python -m xpilot_bot.train --steps 200000 --envs 4 --fps 200
python -m xpilot_bot.benchmark --model ai/checkpoints/ppo_final.zip
python -m xpilot_bot.benchmark --random      # always compare against this
```

Training runs a curriculum — **navigate, then dodge, then combat** — carrying
the policy forward between stages. The reason for staging is that firing is
only rewarded when it connects, and it cannot connect until the agent can
already fly and aim, so an agent dropped straight into combat has no gradient
to climb and settles for sitting still.

### One setting that matters more than the rest

`frames_per_step` defaults to 10, and the default used to be 1. That was
wrong in a way worth knowing about: at 200 fps a frame is 5 ms, so a 500-step
episode was **two and a half seconds of game time**. Measured, the ship never
reached a non-zero speed and no opponent ever came into view — the environment
looked like it was working and was teaching nothing. Ten frames makes a step
50 ms, about a human reaction time.

### On win rates

They are measured, from the server's own death notices, and the benchmark
reports them. Getting there meant fixing two bugs that had made the whole
environment quietly wrong, both of which looked like facts about the game
rather than defects in the client.

**The client went deaf when play started.** Reliable data is piggybacked onto
frame packets once the game begins, and the client only inspected the first
byte of each datagram. So it read all of setup correctly and then heard
nothing: no scores, no kills, no player joins. Having stopped acknowledging
anything, it was dropped by the server about fifteen seconds in — every
training episode longer than that was ending in a disconnection dressed up
as an episode end.

**Death was detected by a signal that never fires.** `Receive_self` in the C
client notes that a frame without PKT_SELF means the player is "damaged,
dead, paused or has game over", which makes watching for missing PKT_SELF
look like the obvious approach. Measured against a live server, an idle bot
died **ten times in ninety seconds without a single frame missing its
PKT_SELF** — the server reports the ship straight through death and respawn.
No episode had ever terminated on death and the death penalty had never once
been applied.

Both are why the standing note that "the robots never kill the bot" was
wrong. They kill it constantly; nobody was listening. An idle bot dies five
times in seventy seconds, and every one of those deaths was announced:

    Probe was killed by a shot from Boson.

Kills come from those notices rather than from `PKT_SCORE`, whose life count
never changes on a map with unlimited lives. Chat is excluded — otherwise a
player could type a death notice and be believed.

## Status

Phases 6a and 6b are met. Both of the game's packet streams decode: frames at
0 truncated out of 2,250 against a live server with four robots, and the
reliable sub-stream cleanly through setup and play, checked continuously in
CI by `tools/check_reliable.py`.

Phase 6c trains and benchmarks. A 180k-step curriculum policy against a
random baseline, 15 and 20 episodes respectively on `dodgers-robots.xp2`:

| | random | trained |
|---|---|---|
| mean reward | 16.28 (sd 24.40) | 14.79 (sd 23.74) |
| mean episode length | 155 steps | **192 steps** |
| mean aim error | 1.66 rad | **1.14 rad** |
| **score, by the server's own reckoning** | **−151.01** | **+264.69** |
| kills / deaths | 15 / 20 | 11 / 14 |
| win rate | 43% | 44% |
| mean speed | 7.2 | 3.4 |

Read that carefully, because the headline is not the win rate. Kills are a
tie and the reward difference is inside the noise — the standard deviations
are larger than the gap, which is what a 25-point kill bonus does to a
15-episode sample.

What is not inside the noise is the **score**, and it is the one number here
that the training could not have gamed: the server computes it, and it owes
nothing to the reward function in `env.py`. The trained policy ends 416
points ahead of random across the two runs. It also stays alive about a
quarter longer. So there is something real, and it is not "learned to shoot
people" — it is closer to "learned not to throw the ship away".

The policy is not degenerate this time: ten distinct actions with the most
common on 50% of steps, against an earlier one that sat on a single action
for 85% and never moved.

Two things learned the hard way, both worth more than the numbers:

**Measure the ship before measuring the policy.** Every result before
2026-08-27 was void because the ship could not turn — `MIN_PLAYER_TURNSPEED`
is 0.0 and a client that never sends `PKT_TURNSPEED` is welded to one
heading, silently. The agent was being rewarded for aiming while holding no
action that could change where it aimed. Note how much better *random* does
once that is fixed: 15 kills against 8, 43% against 29%. Most of what this
benchmark was measuring was whether the ship worked.

**Reward what you actually want, at a rate that outbids the alternatives.**
With aim worth 0.05 a step, a policy that parked and fired straight ahead
earned about as much per episode from aiming (5.5) as from a kill (5.0) — and
aiming is safe. It learned to park: 85% of steps "fire", 14% "shield", under
0.5% turns, mean speed 0.2, zero kills in ten episodes. Its aim error looked
excellent at 0.72 rad, which is exactly the trap: a stationary ship facing
where opponents arrive from scores well without having learned anything.
Kills are now worth 25 and aim 0.01, and the benchmark reports mean speed and
action concentration so a parked policy is visible at a glance rather than
after an hour of investigation.

The `hunter` example remains a demonstration rather than a good player:
tracking one target it holds a mean aim error of about 19 heading units
against roughly 32 for random, and is inside its firing cone about a quarter
of the time. It has no lead, no evasion and no memory.
