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
    "navigate": {"alive": 0.01, "fuel": 0.5, "aim": 0.00, "speed": 0.05},
    "dodge":    {"alive": 0.02, "fuel": 0.3, "aim": 0.00, "speed": 0.02},
    "combat":   {"alive": 0.01, "fuel": 0.2, "aim": 0.05, "speed": 0.01},
}

#: Robots present at each stage. Navigation is learned on an empty map.
STAGE_ROBOTS = {"navigate": 0, "dodge": 2, "combat": 4}

#: How many other ships appear in the observation, nearest first.
MAX_TRACKED_SHIPS = 4

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
        if stage not in STAGES:
            raise ValueError(f"unknown stage {stage!r}; expected one of "
                             f"{sorted(STAGES)}")
        self.stage = stage
        self._server = server

        self.action_space = spaces.Discrete(len(ACTIONS))
        obs_len = 6 + 5 * MAX_TRACKED_SHIPS
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(obs_len,), dtype=np.float32
        )

        self._client: Client | None = None
        self._steps = 0
        self._prev_fuel: float | None = None
        self._prev_damaged = False
        self._last_obs: np.ndarray | None = None
        #: Deaths the server had announced when the episode started. reset()
        #: makes a fresh connection, so this is always 0 in practice; it is
        #: kept explicit rather than assumed.
        self._deaths_at_step = 0

    # ------------------------------------------------------------ gym API

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self._close_client()

        self._client = Client(
            host=self.host, port=self.port,
            nick=self.nick, user=self.nick, fps=self.fps,
        )
        self._client.connect()
        self._steps = 0
        self._prev_fuel = None
        self._prev_damaged = False
        self._deaths_at_step = self._death_count()

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
            info["scoreboard"] = rel.board.summary()
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
        others.sort(key=lambda sh: (sh.x - me.x) ** 2 + (sh.y - me.y) ** 2)

        for i in range(MAX_TRACKED_SHIPS):
            if i < len(others):
                sh = others[i]
                dx, dy = sh.x - me.x, sh.y - me.y
                dist = math.hypot(dx, dy)
                bearing = math.atan2(dy, dx)
                err = (bearing - heading + math.pi) % (2 * math.pi) - math.pi
                obs += [dx / s, dy / s, dist / s, err / math.pi, 1.0]
            else:
                obs += [0.0, 0.0, 0.0, 0.0, 0.0]

        return np.asarray(obs, dtype=np.float32)

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

        if w["aim"]:
            others = [sh for sh in frame.ships
                      if (sh.x, sh.y) != (me.x, me.y)]
            if others:
                nearest = min(
                    others,
                    key=lambda sh: (sh.x - me.x) ** 2 + (sh.y - me.y) ** 2)
                heading = 2 * math.pi * me.heading / HEADING_STEPS
                bearing = math.atan2(nearest.y - me.y, nearest.x - me.x)
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
