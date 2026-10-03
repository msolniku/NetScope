import argparse
import subprocess
import sys
import time
from datetime import datetime, timedelta

from config.settings import DEFAULT_INTERVAL_SEC
from collectors.router_collector import collect_for_duration


# --------------------------------------------------
# Helpers
# --------------------------------------------------

def run_module(module_name: str) -> str:
    """
    Run a Python module via `python -m`.

    Returns:
        "ok"       — success
        "no_data"  — module exited with code 2 (not enough data yet)
        "error"    — any other non-zero exit code
    """
    print(f"\n{'='*64}")
    print(f"  Running: {module_name}")
    print("=" * 64)

    result = subprocess.run([sys.executable, "-m", module_name])

    if result.returncode == 0:
        return "ok"
    if result.returncode == 2:
        print(f"⏸  {module_name} skipped (no data yet).")
        return "no_data"

    print(f"!! {module_name} exited with code {result.returncode}")
    return "error"


def run_analyze_chain() -> bool:
    """
    Run snapshot_differ → dataset_builder → explore.

    If any step reports "no data yet" (exit 2), stop the chain cleanly —
    this is not an error.
    Returns True if chain completed or was gracefully short-circuited,
    False only on a real error.
    """
    chain = [
        "analysis.snapshot_differ",
        "analysis.dataset_builder",
        "analysis.explore",
        "ml.train",
        "ml.predict",
    ]

    for module in chain:
        status = run_module(module)

        if status == "ok":
            continue
        if status == "no_data":
            print("\n⏸  Analysis chain stopped early: not enough data yet.")
            print("   (This is normal — collect more snapshots first.)")
            return True
        # status == "error"
        return False

    return True


def timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# --------------------------------------------------
# Commands
# --------------------------------------------------

def cmd_collect(hours: float, interval: int, analyze: bool) -> None:
    print(f"\n[{timestamp()}] Starting collection for {hours}h ...")
    collect_for_duration(hours=hours, interval=interval)

    if analyze:
        print(f"\n[{timestamp()}] Running analysis chain ...")
        run_analyze_chain()
    else:
        print(f"\n[{timestamp()}] Collection done. (analysis skipped)")


def cmd_analyze_only() -> None:
    print(f"\n[{timestamp()}] Running analysis chain ...")
    run_analyze_chain()


def cmd_isp(analyze: bool) -> None:
    print(f"\n[{timestamp()}] Refreshing ISP data ...")
    status = run_module("collectors.isp_collector")

    if status == "ok" and analyze:
        print(f"\n[{timestamp()}] Running analysis chain ...")
        run_analyze_chain()


def cmd_daily(start_hour: int, stop_hour: int, interval: int) -> None:
    print(f"\nDaily mode: collect from {start_hour:02d}:00 to {stop_hour:02d}:00")
    print("Press Ctrl+C to stop the daily loop.\n")

    while True:
        now = datetime.now()
        today_start = now.replace(hour=start_hour, minute=0, second=0, microsecond=0)
        today_stop  = now.replace(hour=stop_hour,  minute=0, second=0, microsecond=0)

        if now < today_start:
            wait = (today_start - now).total_seconds()
            print(f"\n[{timestamp()}] Not yet in window. "
                  f"Sleeping {int(wait)}s until {today_start}")
            time.sleep(wait)
            continue

        if now >= today_stop:
            tomorrow_start = today_start + timedelta(days=1)
            wait = (tomorrow_start - now).total_seconds()
            print(f"\n[{timestamp()}] Past today's window. "
                  f"Sleeping {int(wait)}s until {tomorrow_start}")
            time.sleep(wait)
            continue

        hours_left = (today_stop - now).total_seconds() / 3600
        print(f"\n[{timestamp()}] Inside window. "
              f"Collecting for {hours_left:.2f}h ...")

        try:
            collect_for_duration(hours=hours_left, interval=interval)
        except KeyboardInterrupt:
            print("\nStopped by user.")
            return

        print(f"\n[{timestamp()}] Running analysis chain ...")
        run_analyze_chain()

        time.sleep(60)


# --------------------------------------------------
# CLI
# --------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="pipeline",
        description="Internet Usage Intelligence Agent — orchestrator",
    )
    sub = parser.add_subparsers(dest="command")

    p_collect = sub.add_parser("collect", help="Collect router snapshots for N hours")
    p_collect.add_argument("--hours", type=float, required=True)
    p_collect.add_argument("--interval", type=int, default=DEFAULT_INTERVAL_SEC)
    p_collect.add_argument("--no-analyze", action="store_true")

    sub.add_parser("analyze", help="Run analysis chain only")

    p_isp = sub.add_parser("isp", help="Refresh ISP data")
    p_isp.add_argument("--no-analyze", action="store_true")

    p_daily = sub.add_parser("daily", help="Daily schedule")
    p_daily.add_argument("--start", type=int, required=True,
                         help="Start hour, e.g. 8 for 08:00")
    p_daily.add_argument("--stop", type=int, required=True,
                         help="Stop hour, e.g. 23 for 23:00")
    p_daily.add_argument("--interval", type=int, default=DEFAULT_INTERVAL_SEC)

    args = parser.parse_args()

    if args.command == "collect":
        cmd_collect(args.hours, args.interval, analyze=not args.no_analyze)
    elif args.command == "analyze":
        cmd_analyze_only()
    elif args.command == "isp":
        cmd_isp(analyze=not args.no_analyze)
    elif args.command == "daily":
        cmd_daily(args.start, args.stop, args.interval)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()