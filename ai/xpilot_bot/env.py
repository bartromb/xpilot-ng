"""A Gymnasium environment wrapping the XPilot NG client.

The agent plays against an unmodified server, seeing only what a human
player's client is sent and acting only through keys a human can press. That
constraint is the point: an agent trained here is playing the real game, not a
convenient approximation of it.

    pip install "xpilot-bot[rl]"

    import gymnasium as gym
    from xpilot_bot.env import XPilotEnv

    env = XPilotEnv(host="localhost", port=15345)
    obs, info = env.reset()
    obs, reward, terminated, truncated, info = env.step(env.action_space.sample())

The server must already be running. `ServerProcess` in this module can start
one for you, including at faster than realtime.

Requires gymnasium and numpy; the rest of xpilot_bot does not.
"""

from __future__ import annotations

import math
import subprocess
import time

import numpy as np

try:
    import gymnasium as gym
    from gymnasium import spaces
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        'XPilotEnv needs gymnasium. Install with: pip install "xpilot-bot[rl]"'
    ) from exc

from .client import Client, ProtocolError
from .frames import world_shots, wrapped_delta
from . import protocol as p

#: Actions, as combinations of held keys. XPilot input is continuous -- keys
#: are held rather than tapped -- so each action is "the set of keys held for
#: this step" rather than an event.
ACTIONS: list[tuple[int, ...]] = [
    (),                                        # coast
    (p.KEY_THRUST,),
    (p.KEY_TURN_LEFT,),
    (p.KEY_TURN_RIGHT,),
    (p.KEY_THRUST, p.KEY_TURN_LEFT),
    (p.KEY_THRUST, p.KEY_TURN_RIGHT),
    (p.KEY_FIRE_SHOT,),
    (p.KEY_THRUST, p.KEY_FIRE_SHOT),
    (p.KEY_TURN_LEFT, p.KEY_FIRE_SHOT),
    (p.KEY_TURN_RIGHT, p.KEY_FIRE_SHOT),
    (p.KEY_SHIELD,),
]

#: Curriculum stages, as reward weights.
#:
#: The roadmap notes that learning combat directly tends to stall, which is
#: the usual finding: firing is only rewarded when it connects, and it cannot
#: connect until the agent can already fly and aim. So flying is rewarded
#: first, then staying alive near opponents, then aiming, and only then is the
#: survival bonus reduced so that fighting is worth the risk.
#:
#: alive   per step, for existing
#: fuel    change in fuel fraction; discourages pointless thrusting
#: aim     for pointing at the nearest ship
#: speed   for moving at all; without it "sit still" is a local optimum
STAGES = {
    "navigate": {"alive": 0.01, "fuel": 0.5, "aim": 0.00, "speed": 0.05, "kill": 0.0},
    "dodge":    {"alive": 0.02, "fuel": 0.3, "aim": 0.00, "speed": 0.02, "kill": 0.0},
    "combat":   {"alive": 0.01, "fuel": 0.2, "aim": 0.05, "speed": 0.01, "kill": 5.0},
}

#: Robots present at each stage. Navigation is learned on an empty map.
STAGE_ROBOTS = {"navigate": 0, "dodge": 2, "combat": 4}

#: How many other ships appear in the observation, nearest first.
MAX_TRACKED_SHIPS = 4

#: How many incoming shots appear in the observation, nearest first.
#:
#: Without these the agent cannot see bullets at all, which makes the
#: roadmap's "dodge" stage a stage about avoiding *ships*. Shots are the
#: densest thing in a frame -- a few thousand in a busy ten seconds -- so
#: only the nearest handful are worth the observation width.
MAX_TRACKED_SHOTS = 4

HEADING_STEPS = 128


class ServerProcess:
    """Runs a dedicated server for one environment.

    Each environment needs its own server on its own port: XPilot has no
    notion of parallel independent matches inside one process, so N parallel
    environments means N servers. They are cheap -- a headless server with a
    couple of robots is a few MB.
    """

    def __init__(
        self,
        binary: str = "./build/bin/xpilot-ng-server",
        map_file: str = "lib/maps/dodgers-robots.xp2",
        port: int = 15345,
        robots: int = 2,
        fps: int = 50,
        quiet: bool = True,
    ) -> None:
        self.port = port
        self.fps = fps
        self._proc = subprocess.Popen(
            [
                binary,
                "-map", map_file,
                "-port", str(port),
                "-maxRobots", str(robots),
                "-minRobots", str(robots),
                "-framesPerSecond", str(fps),
                # Without these the server exits when the last human leaves,
                # which for a bot-only server means immediately.
                "-noQuit", "-idleRun",
                # Nothing should phone home during training.
                "-reportToMetaServer", "false",
            ],
            stdout=subprocess.DEVNULL if quiet else None,
            stderr=subprocess.DEVNULL if quiet else None,
        )
        # Give it time to bind before anyone connects.
        time.sleep(1.5)

    def close(self) -> None:
        if self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()

    def __enter__(self) -> "ServerProcess":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class XPilotEnv(gym.Env):
    """One bot in one XPilot game.

    Observation (float32), all scaled to roughly [-1, 1]:

        0     fuel / fuel_max
        1,2   own velocity
        3,4   heading as (cos, sin) -- continuous across the 127->0 wrap,
              which a raw heading number is not
        5     1 if damaged
        then, per tracked ship, nearest first:
        +0,1  relative position
        +2    distance
        +3    bearing error: where it is, relative to where we point
        +4    1 if this slot holds a real ship, 0 if padding

    The presence flag matters. Without it a padded slot of zeros is
    indistinguishable from a ship at exactly our position.
    """

    metadata = {"render_modes": []}

    def __init__(
        self,
        host: str = "localhost",
        port: int = 15345,
        nick: str = "rl",
        fps: int = 50,
        max_steps: int = 2000,
        frames_per_step: int = 10,
        world_scale: float = 3000.0,
        death_frames: int = 15,
        death_penalty: float = 1.0,
        reuse_connection: bool = True,
        edge_wrap: bool = True,
        include_shots: bool = False,
        stage: str = "combat",
        server: ServerProcess | None = None,
    ) -> None:
        super().__init__()
        self.host = host
        self.port = port
        self.nick = nick
        self.fps = fps
        self.max_steps = max_steps
        # One frame per step is far too fine to act on. At 200 fps a frame is
        # 5ms, so a 500-step episode would be two and a half seconds of game
        # time -- measured, the ship never even reached a non-zero speed and
        # no opponent ever came into view. Ten frames makes a step 50ms at
        # 200 fps, which is about a human reaction and enough for an action to
        # have a visible effect.
        self.frames_per_step = frames_per_step
        self.world_scale = world_scale
        # A frame with no PKT_SELF means "not actively playing": dead,
        # damaged, paused or game over (see Receive_self in netclient.c).
        # A run of them is how death is detected -- the protocol has no
        # "you died" packet the client can simply read.
        self.death_frames = death_frames
        self.death_penalty = death_penalty
        self.reuse_connection = reuse_connection
        self.edge_wrap = edge_wrap
        # Changing this changes the observation width, so a checkpoint and
        # the benchmark that scores it have to agree on it.
        self.include_shots = include_shots
        if stage not in STAGES:
            raise ValueError(f"unknown stage {stage!r}; expected one of "
                             f"{sorted(STAGES)}")
        self.stage = stage
        self._server = server

        self.action_space = spaces.Discrete(len(ACTIONS))
        obs_len = 6 + 5 * MAX_TRACKED_SHIPS
        if include_shots:
            obs_len += 5 * MAX_TRACKED_SHOTS
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(obs_len,), dtype=np.float32
        )

        self._client: Client | None = None
        self._steps = 0
        self._prev_fuel: float | None = None
        self._prev_damaged = False
        self._last_obs: np.ndarray | None = None
        self._kills_seen = 0
        #: Deaths the server had announced when the episode started. reset()
        #: makes a fresh connection, so this is always 0 in practice; it is
        #: kept explicit rather than assumed.
        self._deaths_at_step = 0
        self._deaths_at_reset = 0
        self._kills_at_reset = 0

    # ------------------------------------------------------------ gym API

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)

        # Reconnecting between episodes is the tidy thing to do and it is
        # expensive: the handshake is a two-phase exchange with a setup
        # transfer, and with episodes ending on death rather than on the step
        # limit it happens every few seconds. Measured, it was most of the
        # difference between 56 steps/s on the empty map and 25 in combat.
        #
        # It is also unnecessary. XPilot respawns a dead ship on the same
        # connection -- that is what makes an idle bot die ten times in
        # ninety seconds rather than once -- so a new episode can simply
        # carry on. The counters this class keeps are already differences
        # against where the episode started, precisely so that works.
        if self._client is None or not self.reuse_connection:
            self._close_client()
            self._client = Client(
                host=self.host, port=self.port,
                nick=self.nick, user=self.nick, fps=self.fps,
            )
            self._client.connect()
        else:
            self._client.release_all()
            self._client.send_keys()

        self._steps = 0
        self._prev_fuel = None
        self._prev_damaged = False
        self._deaths_at_step = self._death_count()
        self._kills_seen = self._kill_count()
        self._deaths_at_reset = self._deaths_at_step
        self._kills_at_reset = self._kills_seen

        frame = self._await_frame()
        obs = self._observe(frame)
        self._last_obs = obs
        return obs, self._info()

    def _info(self, **extra) -> dict:
        """Per-step diagnostics, including what the reliable stream says.

        The scoreboard is the only source of scores and kills: none of it is
        on the frame stream, which is why win rates were unmeasurable until
        that stream was decoded. It is reported rather than rewarded --
        rewarding it directly would be tempting but it arrives late and
        irregularly, which makes for a badly-shaped signal.
        """
        info = dict(extra)
        rel = getattr(self._client, "reliable", None)
        if rel is not None:
            board = rel.board.summary()
            # The board counts a whole connection, and a connection now spans
            # many episodes. Anything summed per episode has to be a delta
            # against where this episode started, or twenty single-death
            # episodes add up to two hundred deaths.
            board["episode_kills"] = self._kill_count() - self._kills_at_reset
            board["episode_deaths"] = self._death_count() - self._deaths_at_reset
            info["scoreboard"] = board
            info["reliable_desynced"] = rel.desynced
        return info

    def step(self, action: int):
        if self._client is None:
            raise RuntimeError("step() before reset()")

        keys = ACTIONS[int(action)]
        self._client.release_all()
        for k in keys:
            self._client.press(k)

        try:
            self._client.send_keys()
            frame = None
            for _ in range(self.frames_per_step):
                frame, died = self._next_frame()
                if died:
                    # Repeat the last observation rather than inventing one:
                    # there is no own-ship state to report while dead.
                    obs = (self._last_obs
                           if self._last_obs is not None
                           else np.zeros(self.observation_space.shape,
                                         dtype=np.float32))
                    self._steps += 1
                    return obs, -self.death_penalty, True, False, self._info(died=True)
        except ProtocolError:
            # Dropped mid-episode. Ending it is honest; pretending otherwise
            # would feed the agent an observation that never happened.
            obs = np.zeros(self.observation_space.shape, dtype=np.float32)
            return obs, 0.0, True, False, self._info(disconnected=True)

        self._steps += 1
        obs = self._observe(frame)
        self._last_obs = obs
        reward = self._reward(frame)
        truncated = self._steps >= self.max_steps
        return obs, reward, False, truncated, self._info(frame=frame.loops)

    def close(self):
        self._close_client()
        if self._server is not None:
            self._server.close()
            self._server = None

    # -------------------------------------------------------------- innards

    def _close_client(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except OSError:
                pass
            self._client = None

    def _await_frame(self, timeout: float = 5.0):
        """Block until a frame carrying own-ship state arrives."""
        assert self._client is not None
        deadline = time.time() + timeout
        while time.time() < deadline:
            frame = self._client.poll()
            if frame is not None and frame.self_ is not None:
                return frame
        raise ProtocolError("no frame from the server within the timeout")

    def _next_frame(self, timeout: float = 5.0):
        """Return (frame, died).

        Death is taken from the server's own notices on the reliable stream,
        which is the only place it is stated. The obvious alternative --
        watching for frames that arrive with no own-ship state -- looks
        reasonable and detects nothing: measured against a live server, an
        idle bot died ten times in ninety seconds without a single frame
        missing its PKT_SELF. The server keeps reporting the ship straight
        through death and respawn, so an episode using that signal never
        terminates and the agent is never told it died.

        A run of frames with no own-ship state is still watched, because it
        does happen while paused or between rounds, but it is reported as a
        stall rather than as death.
        """
        assert self._client is not None
        missing = 0
        deadline = time.time() + timeout
        while time.time() < deadline:
            frame = self._client.poll()
            if frame is None:
                continue
            if self._death_count() > self._deaths_at_step:
                self._deaths_at_step = self._death_count()
                return frame, True
            if frame.self_ is not None:
                return frame, False
            missing += 1
            if missing >= self.death_frames:
                # Not death: the ship state simply stopped arriving. Ending
                # the episode is still right, but calling it a death would
                # be a guess.
                return frame, False
        raise ProtocolError("no frame from the server within the timeout")

    def _death_count(self) -> int:
        """How many times the server says we have died this connection."""
        rel = getattr(self._client, "reliable", None)
        if rel is None:
            return 0
        me = rel.board.me
        return me.deaths if me is not None else 0

    def _kill_count(self) -> int:
        """How many kills the server has credited us this connection."""
        rel = getattr(self._client, "reliable", None)
        if rel is None:
            return 0
        me = rel.board.me
        return me.kills if me is not None else 0

    def _world_size(self) -> tuple[float, float]:
        """Map dimensions in pixels, from the setup blob the server sent.

        Another thing that only exists because the reliable stream is
        decoded: the frame stream never says how big the world is.
        """
        rel = getattr(self._client, "reliable", None)
        setup = rel.board.setup if rel is not None else None
        if setup is None or setup.width <= 0 or setup.height <= 0:
            return (0.0, 0.0)
        return (float(setup.width), float(setup.height))

    def _delta(self, ax, ay, bx, by):
        """Vector from a to b, the short way round a wrapping world.

        `dodgers-robots.xp2` sets `edgeWrap="yes"`, and most XPilot maps do:
        flying off the right edge brings you back on the left. Subtracting
        coordinates therefore gives the wrong answer for any pair more than
        half the map apart -- and gives it confidently, as a bearing that can
        be a full 180 degrees off. Two ships closing on each other across the
        seam read as the furthest apart on the map.

        Falls back to a plain difference when the world size is unknown,
        which is right for a map that does not wrap.
        """
        w, h = self._world_size() if self.edge_wrap else (0.0, 0.0)
        return wrapped_delta(w, h, ax, ay, bx, by)

    def _observe(self, frame) -> np.ndarray:
        me = frame.self_
        s = self.world_scale
        heading = 2 * math.pi * me.heading / HEADING_STEPS

        obs = [
            me.fuel / max(me.fuel_max, 1),
            me.vx / 50.0,
            me.vy / 50.0,
            math.cos(heading),
            math.sin(heading),
            1.0 if frame.damaged else 0.0,
        ]

        others = [sh for sh in frame.ships if (sh.x, sh.y) != (me.x, me.y)]
        deltas = {id(sh): self._delta(me.x, me.y, sh.x, sh.y) for sh in others}
        others.sort(key=lambda sh: deltas[id(sh)][0] ** 2 + deltas[id(sh)][1] ** 2)

        for i in range(MAX_TRACKED_SHIPS):
            if i < len(others):
                sh = others[i]
                dx, dy = deltas[id(sh)]
                dist = math.hypot(dx, dy)
                bearing = math.atan2(dy, dx)
                err = (bearing - heading + math.pi) % (2 * math.pi) - math.pi
                obs += [dx / s, dy / s, dist / s, err / math.pi, 1.0]
            else:
                obs += [0.0, 0.0, 0.0, 0.0, 0.0]

        if self.include_shots:
            obs += self._shot_features(frame, me, heading)

        return np.asarray(obs, dtype=np.float32)

    def _shot_features(self, frame, me, heading) -> list:
        """The nearest few shots, in the same shape as the ship slots.

        These are *all* shots, including our own. PKT_FASTSHOT carries no
        owner and no velocity -- just a tile index and a byte pair per shot
        -- so nothing here can distinguish a bullet flying at us from one we
        just fired. That is a real limitation rather than an oversight: the
        information is not on the wire. It is survivable because our own fire
        correlates with the action we just chose, which the agent knows, so
        it is learnable noise rather than a confound.
        """
        s = self.world_scale
        shots = world_shots(frame)

        rows = []
        for sx, sy, _kind in shots:
            dx, dy = self._delta(me.x, me.y, sx, sy)
            d2 = dx * dx + dy * dy
            # Our own muzzle flash sits on top of us every time we fire, and
            # reporting it as the nearest threat would drown out real ones.
            if d2 < 400:
                continue
            rows.append((d2, dx, dy))
        rows.sort(key=lambda r: r[0])

        out = []
        for i in range(MAX_TRACKED_SHOTS):
            if i < len(rows):
                d2, dx, dy = rows[i]
                dist = math.sqrt(d2)
                bearing = math.atan2(dy, dx)
                err = (bearing - heading + math.pi) % (2 * math.pi) - math.pi
                out += [dx / s, dy / s, dist / s, err / math.pi, 1.0]
            else:
                out += [0.0, 0.0, 0.0, 0.0, 0.0]
        return out

    def _reward(self, frame) -> float:
        """Reward for the current curriculum stage.

        Kept simple and legible on purpose. Every term is something a person
        can check against behaviour on screen, which matters when an agent
        does something strange and the question is whether the reward asked
        for it.
        """
        w = STAGES[self.stage]
        me = frame.self_
        reward = w["alive"]

        fuel = me.fuel / max(me.fuel_max, 1)
        if self._prev_fuel is not None:
            reward += (fuel - self._prev_fuel) * w["fuel"]
        self._prev_fuel = fuel

        if frame.damaged and not self._prev_damaged:
            reward -= 1.0
        self._prev_damaged = frame.damaged

        speed = math.hypot(me.vx, me.vy)
        reward += w["speed"] * min(speed / 20.0, 1.0)

        # The only term that is the actual objective rather than a proxy for
        # it. It is sparse and it arrives a frame or two late, which is why
        # the aim and survival terms exist at all -- but leaving it out
        # entirely meant an agent could satisfy every term in this function
        # without ever winning a fight.
        if w["kill"]:
            kills = self._kill_count()
            if kills > self._kills_seen:
                reward += w["kill"] * (kills - self._kills_seen)
                self._kills_seen = kills

        if w["aim"]:
            others = [sh for sh in frame.ships
                      if (sh.x, sh.y) != (me.x, me.y)]
            if others:
                deltas = {id(sh): self._delta(me.x, me.y, sh.x, sh.y)
                          for sh in others}
                nearest = min(
                    others,
                    key=lambda sh: deltas[id(sh)][0] ** 2 + deltas[id(sh)][1] ** 2)
                heading = 2 * math.pi * me.heading / HEADING_STEPS
                dx, dy = deltas[id(nearest)]
                bearing = math.atan2(dy, dx)
                err = abs((bearing - heading + math.pi) % (2 * math.pi)
                          - math.pi)
                reward += w["aim"] * (1.0 - err / math.pi)

        return float(reward)


def make_parallel(
    n: int,
    base_port: int = 15400,
    fps: int = 200,
    robots: int | None = None,
    stage: str = "combat",
    map_file: str = "lib/maps/dodgers-robots.xp2",
    binary: str = "./build/bin/xpilot-ng-server",
    **env_kwargs,
):
    """Start n independent environments, each with its own server.

    XPilot has no concept of separate matches inside one server process, so
    parallelism means one server per environment, each on its own port. They
    are cheap: a headless server with a couple of robots is a few MB and
    little CPU when nothing is happening.

    Returns (envs, servers). Close the envs; each closes its own server.
    """
    if robots is None:
        robots = STAGE_ROBOTS[stage]

    envs, servers = [], []
    try:
        for i in range(n):
            port = base_port + i
            srv = ServerProcess(binary=binary, map_file=map_file, port=port,
                                robots=robots, fps=fps)
            servers.append(srv)
            envs.append(XPilotEnv(port=port, nick=f"rl{i}", fps=fps,
                                  stage=stage, server=srv, **env_kwargs))
        return envs, servers
    except Exception:
        for e in envs:
            e.close()
        for s in servers:
            s.close()
        raise
