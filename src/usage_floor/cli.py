"""Command-line entry point."""

from __future__ import annotations

import argparse
import json
import sys

from usage_floor import __version__, menu, store, supervisor, system
from usage_floor.paths import resolve

DESCRIPTION = """\
Keep a usage reserve on each subscription plan used by T3 Code agents.

Run without a command to open the menu. Pick a plan, pick one of its usage windows and set the
share that must stay unused. The supervisor reads live usage every two minutes and parks agents on
a plan that drops below its floor, then resumes them when the window resets.
"""


def _write(text: str) -> None:
    sys.stdout.write(text + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="usage-floor", description=DESCRIPTION,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version", version=f"usage-floor {__version__}")
    commands = parser.add_subparsers(dest="command", metavar="command")
    run = commands.add_parser("run", help="run the supervisor in the foreground")
    run.add_argument("--once", action="store_true", help="make one pass and exit")
    run.add_argument("--dry-run", action="store_true", help="show decisions without acting")
    commands.add_parser("status", help="print settings, state and supervisor status as JSON")
    commands.add_parser("start", help="start the supervisor in the background")
    commands.add_parser("stop", help="stop the background supervisor")
    autostart = commands.add_parser("autostart", help="start the supervisor at sign-in (Windows)")
    autostart.add_argument("state", choices=("on", "off"))
    args = parser.parse_args(argv)
    paths = resolve()

    if args.command is None:
        menu.run(paths)
    elif args.command == "run" and (args.once or args.dry_run):
        _write(json.dumps(supervisor.poll(paths, dry_run=args.dry_run), indent=2, default=str))
    elif args.command == "run":
        supervisor.run_forever(paths)
    elif args.command == "status":
        _write(json.dumps({
            "supervisorPid": supervisor.running_pid(paths),
            "autostart": system.autostart_enabled(),
            "paths": {"home": str(paths.home), "t3Home": str(paths.t3_home), "t3Cli": paths.t3_cli},
            "config": store.load(paths.config, store.DEFAULT_CONFIG),
            "state": store.load(paths.state, store.DEFAULT_STATE),
        }, indent=2))
    elif args.command == "start":
        _write(supervisor.start(paths))
    elif args.command == "stop":
        _write(supervisor.stop(paths))
    elif args.command == "autostart":
        _write(system.set_autostart(args.state == "on"))
    return 0
