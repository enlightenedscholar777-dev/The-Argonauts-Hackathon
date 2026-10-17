"""
Simulator entry point.

Run the demo scenario:
    python main.py

Run with fault injection:
    python main.py --fault drop_sonar
    python main.py --fault disable_ai
    python main.py --fault clock_jump
    python main.py --fault event_flood
    python main.py --fault replay_old_data

Run with verbose logging:
    python main.py --verbose
"""

from __future__ import annotations

import argparse
import logging
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description="Maritime harbour simulator")
    parser.add_argument(
        "--steps", type=int, default=60,
        help="Number of simulation ticks (default: 60 × 5 s = 5 min)",
    )
    parser.add_argument(
        "--fault",
        choices=["drop_sonar", "disable_ai", "clock_jump", "event_flood", "replay_old_data"],
        default=None,
        help="Inject a fault for demonstration purposes",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Enable DEBUG logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)-8s %(name)s: %(message)s",
        stream=sys.stdout,
    )

    # Import here to avoid circular issues during module scan
    from simulator.orchestrator.runner import ScenarioConfig, SimulatorRunner

    scenario = ScenarioConfig.demo()
    runner   = SimulatorRunner(scenario)

    # Fault injection
    if args.fault == "drop_sonar":
        runner.faults.drop_sensor("sonar-01")
    elif args.fault == "disable_ai":
        runner.faults.disable_ai()
    elif args.fault == "clock_jump":
        runner.faults.set_clock_jump(7200.0)   # 2-hour future jump → pipeline rejects
    elif args.fault == "event_flood":
        runner.faults.enable_event_flood()
    elif args.fault == "replay_old_data":
        runner.faults.enable_replay_old_data()

    print(f"\n=== Running '{scenario.name}' for {args.steps} ticks ===\n")
    runner.run(steps=args.steps)
    print("\n=== Simulation complete ===")


if __name__ == "__main__":
    main()
