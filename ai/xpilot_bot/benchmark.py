"""Benchmark a policy against the built-in server robots.

    python -m xpilot_bot.benchmark --model ai/checkpoints/ppo_final.zip
    python -m xpilot_bot.benchmark --random          # the baseline

Always compare against `--random`. A number like "mean reward 41.2" means
nothing on its own; what matters is whether it beats acting at random on the
same map with the same robots.

On win rates. The roadmap asks for them, and they are not measurable here yet:
scores arrive on the reliable sub-stream, which the client acknowledges but
does not parse, so the bot never learns who killed whom. What is measured is
survival, reward and how well the policy points at opponents -- all of which
come from the frame stream that is decoded. Adding win rates means decoding
the reliable stream, which is a separate piece of work.
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

    for ep in range(episodes):
        env = envs[ep % len(envs)]
        obs, _ = env.reset()
        total, steps = 0.0, 0

        while True:
            if model is None:
                action = env.action_space.sample()
            else:
                action, _ = model.predict(obs, deterministic=True)
            obs, reward, terminated, truncated, info = env.step(int(action))
            total += reward
            steps += 1

            # Aim quality, straight from the observation: the bearing error
            # to the nearest ship, if that slot holds a real one.
            if obs[10] > 0.5:                     # presence flag, first ship
                aim_errors.append(abs(float(obs[9])) * math.pi)

            if terminated or truncated:
                if info.get("died"):
                    deaths += 1
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
    }


def report(name: str, r: dict) -> None:
    print(f"\n{name}")
    print(f"  mean reward      {r['reward_mean']:.2f} "
          f"(sd {r['reward_stdev']:.2f}) over {r['episodes']} episodes")
    print(f"  mean length      {r['length_mean']:.0f} steps")
    print(f"  deaths           {r['deaths']}/{r['episodes']}")
    if r["aim_error_mean"] is not None:
        # pi/2 is the average error of pointing at random.
        print(f"  mean aim error   {r['aim_error_mean']:.2f} rad "
              f"(random ~{math.pi / 2:.2f}) over {r['aim_samples']} samples")
    else:
        print("  mean aim error   no opponents were ever in view")


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
