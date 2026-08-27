"""Benchmark a policy against the built-in server robots.

    python -m xpilot_bot.benchmark --model ai/checkpoints/ppo_final.zip
    python -m xpilot_bot.benchmark --random          # the baseline

Always compare against `--random`. A number like "mean reward 41.2" means
nothing on its own; what matters is whether it beats acting at random on the
same map with the same robots.

On win rates. Scores and kills travel on the reliable sub-stream, not the
frame stream, so they were unmeasurable until that stream was decoded (see
reliable.py). They are now read straight from it: `own deaths` and `kills`
below are the server's own counts, not inferred from missing frames.

Three honest caveats. A run in which nobody dies reports 0-0, which says the
policies never fought, not that they drew. The aim and survival figures come
from the frame stream, which is the more sensitive measure when kill counts
are small. And the "uniform would be 1.57" note beside the aim error is a
sanity floor rather than a baseline -- a genuinely random policy scores
better than uniform here, because the nearest opponent is not uniformly
distributed around the ship. Compare against a `--random` run, not against
that number.

If a checkpoint was trained with --shots it must be evaluated with --shots:
the flag widens the observation, and the model will not load into the wrong
shape.
"""

from __future__ import annotations

import argparse
import math
import statistics
import sys
from pathlib import Path


def evaluate(model, envs, episodes: int, stage: str):
    """Run episodes and collect per-episode statistics."""
    from xpilot_bot.env import HEADING_STEPS

    rewards, lengths, deaths, aim_errors = [], [], 0, []
    # How the policy actually behaves, not just how it scores. A policy that
    # parks and fires straight ahead can post a respectable aim error and a
    # respectable survival time while never fighting; without these two
    # numbers that is invisible in a results table, and it has already
    # happened once.
    action_counts: dict = {}
    speeds = []
    # From the reliable stream: the server's own view of who died.
    own_deaths = kills = 0
    score_total = 0.0
    desynced = False

    for ep in range(episodes):
        env = envs[ep % len(envs)]
        obs, _ = env.reset()
        total, steps = 0.0, 0

        while True:
            if model is None:
                action = env.action_space.sample()
            else:
                action, _ = model.predict(obs, deterministic=True)
            action_counts[int(action)] = action_counts.get(int(action), 0) + 1
            obs, reward, terminated, truncated, info = env.step(int(action))
            # Observation slots 1 and 2 are velocity, scaled by 50.
            speeds.append(math.hypot(float(obs[1]), float(obs[2])) * 50.0)
            total += reward
            steps += 1

            # Aim quality, straight from the observation: the bearing error
            # to the nearest ship, if that slot holds a real one.
            if obs[10] > 0.5:                     # presence flag, first ship
                aim_errors.append(abs(float(obs[9])) * math.pi)

            if terminated or truncated:
                if info.get("died"):
                    deaths += 1
                sb = info.get("scoreboard") or {}
                own_deaths += sb.get("episode_deaths") or 0
                kills += sb.get("episode_kills") or 0
                score_total += sb.get("own_score") or 0.0
                desynced = desynced or bool(info.get("reliable_desynced"))
                break

        rewards.append(total)
        lengths.append(steps)
        print(f"  episode {ep + 1}/{episodes}: reward {total:8.2f}  "
              f"steps {steps:5d}"
              f"{'  DIED' if info.get('died') else ''}", flush=True)

    return {
        "stage": stage,
        "episodes": episodes,
        "reward_mean": statistics.mean(rewards),
        "reward_stdev": statistics.pstdev(rewards) if len(rewards) > 1 else 0.0,
        "length_mean": statistics.mean(lengths),
        "deaths": deaths,
        "aim_error_mean": statistics.mean(aim_errors) if aim_errors else None,
        "aim_samples": len(aim_errors),
        "own_deaths": own_deaths,
        "kills": kills,
        "score_total": score_total,
        "desynced": desynced,
        "top_action_share": (max(action_counts.values()) / sum(action_counts.values())
                             if action_counts else 0.0),
        "distinct_actions": len(action_counts),
        "mean_speed": statistics.mean(speeds) if speeds else 0.0,
    }


def report(name: str, r: dict) -> None:
    print(f"\n{name}")
    print(f"  mean reward      {r['reward_mean']:.2f} "
          f"(sd {r['reward_stdev']:.2f}) over {r['episodes']} episodes")
    print(f"  mean length      {r['length_mean']:.0f} steps")
    print(f"  deaths           {r['deaths']}/{r['episodes']}")
    if r["aim_error_mean"] is not None:
        # pi/2 is what pointing uniformly at random would give. A real random
        # policy does better than that here -- around 1.33 rad -- because the
        # nearest opponent is not uniformly distributed around the ship. So
        # this number is a floor to sanity-check against, not the baseline;
        # the baseline is whatever `--random` measured on the day.
        print(f"  mean aim error   {r['aim_error_mean']:.2f} rad "
              f"(uniform would be {math.pi / 2:.2f}; compare a --random run) "
              f"over {r['aim_samples']} samples")
    else:
        print("  mean aim error   no opponents were ever in view")

    # From the reliable stream.
    print(f"  score (total)    {r['score_total']:.2f}")
    print(f"  kills / deaths   {r['kills']} / {r['own_deaths']}"
          f"   (server's own counts)")
    if r["kills"] == 0 and r["own_deaths"] == 0:
        print("                   nobody died: this is not a draw, it is a "
              "run with no fighting in it")
    else:
        total = r["kills"] + r["own_deaths"]
        print(f"  win rate         {r['kills'] / total:.0%} "
              f"of {total} decided fights")
    print(f"  mean speed       {r['mean_speed']:.1f}")
    print(f"  behaviour        {r['distinct_actions']} distinct actions, "
          f"most-used on {r['top_action_share']:.0%} of steps")
    if r["top_action_share"] > 0.6 or r["mean_speed"] < 2.0:
        print("                   this policy barely moves or barely varies; "
              "treat its aim and survival figures with suspicion")

    if r["desynced"]:
        print("  NOTE: the reliable stream desynchronised, so the counts "
              "above are incomplete")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", help="checkpoint to evaluate (.zip)")
    ap.add_argument("--random", action="store_true",
                    help="evaluate a random policy instead")
    ap.add_argument("--episodes", type=int, default=5)
    ap.add_argument("--stage", default="combat")
    ap.add_argument("--envs", type=int, default=1)
    ap.add_argument("--fps", type=int, default=200)
    ap.add_argument("--max-steps", type=int, default=1000)
    ap.add_argument("--base-port", type=int, default=15700)
    ap.add_argument("--shots", action="store_true",
                    help="show the agent nearby shots. This widens the "
                         "observation, so a checkpoint trained with it can "
                         "only be evaluated with it.")
    ap.add_argument("--binary", default="./build/bin/xpilot-ng-server")
    ap.add_argument("--map", default="lib/maps/dodgers-robots.xp2")
    args = ap.parse_args(argv)

    if not args.model and not args.random:
        ap.error("pass --model or --random")
    if not Path(args.binary).exists():
        print(f"server binary not found: {args.binary}", file=sys.stderr)
        return 1

    model = None
    if args.model:
        try:
            from stable_baselines3 import PPO
        except ImportError:
            print("evaluating a checkpoint needs stable-baselines3",
                  file=sys.stderr)
            return 1
        model = PPO.load(args.model)

    from xpilot_bot.env import make_parallel

    envs, servers = make_parallel(
        args.envs, base_port=args.base_port, fps=args.fps, stage=args.stage,
        max_steps=args.max_steps, binary=args.binary, map_file=args.map,
        include_shots=args.shots,
    )
    try:
        name = f"random policy" if model is None else f"model {args.model}"
        print(f"evaluating {name} on stage {args.stage} "
              f"against {args.episodes} episodes")
        result = evaluate(model, envs, args.episodes, args.stage)
        report(name, result)
    finally:
        for e in envs:
            e.close()
        for s in servers:
            s.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
