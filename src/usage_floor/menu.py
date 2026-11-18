"""The interactive terminal menu."""

from __future__ import annotations

from typing import Any

from usage_floor import humanize, policy, store, supervisor, system
from usage_floor.paths import Paths

RULE = "-" * 96


def _ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except EOFError:
        return "0"


def _show(paths: Paths, plans: list[policy.Plan], config: dict[str, Any], state: dict[str, Any]) -> None:
    pid = supervisor.running_pid(paths)
    print()
    print(
        f"Supervisor: {f'running (pid {pid})' if pid else 'stopped'}   "
        f"Enforcement: {'on' if config.get('enabled', True) else 'OFF'}   "
        f"Start at sign-in: {'yes' if system.autostart_enabled() else 'no'}   "
        f"Last check: {humanize.ago(state.get('lastPoll'))}"
    )
    print(RULE)
    for number, plan in enumerate(plans, 1):
        floors = config["plans"].get(plan["instanceId"], {}).get("floors", {})
        parked = "  ** PARKED **" if plan["instanceId"] in state.get("blocked", {}) else ""
        print(f"{number:>2}. {plan['name']}  [{plan['plan'] or 'no plan info'}]{parked}")
        if not plan["windows"]:
            print("      (T3 reports no usage windows for this plan; a floor cannot be enforced)")
        for window in plan["windows"]:
            left = 100 - float(window["usedPercent"])
            floor = floors.get(window.get("id"))
            mark = f"floor {floor:g}%" if floor is not None else "no floor"
            reset = humanize.when(window.get("resetsAt"))
            print(f"      - {window['label']:<34} {left:5.1f}% left   {mark:<11} resets {reset}")
    print(RULE)


def _pick_plan(plans: list[policy.Plan]) -> policy.Plan | None:
    choice = _ask("Plan number: ")
    if choice.isdigit() and 1 <= int(choice) <= len(plans):
        return plans[int(choice) - 1]
    print("No such plan.")
    return None


def _set_floor(paths: Paths, plans: list[policy.Plan], config: dict[str, Any]) -> None:
    plan = _pick_plan(plans)
    if not plan:
        return
    if not plan["windows"]:
        print("This plan has no usage windows to limit.")
        return
    for number, window in enumerate(plan["windows"], 1):
        print(f"  {number}. {window['label']}")
    choice = _ask("Window number (or 'a' for all of them): ").lower()
    if choice == "a":
        windows = plan["windows"]
    elif choice.isdigit() and 1 <= int(choice) <= len(plan["windows"]):
        windows = [plan["windows"][int(choice) - 1]]
    else:
        print("No such window.")
        return
    raw = _ask("Keep at least this % unused (0-100; 80 parks agents once 20% is used): ")
    try:
        floor = float(raw)
    except ValueError:
        print("Enter a number.")
        return
    if not 0 <= floor <= 100:
        print("Use a value from 0 to 100.")
        return
    entry = config["plans"].setdefault(plan["instanceId"], {"name": plan["name"], "plan": plan["plan"], "floors": {}})
    for window in windows:
        entry["floors"][window["id"]] = floor
    store.save(paths.config, config)
    store.log(paths.events, "floor-set", instance=plan["instanceId"], windows=[w["id"] for w in windows], floor=floor)
    print(f"Saved: {plan['name']} keeps {floor:g}% unused on {', '.join(w['label'] for w in windows)}.")


def _remove_floor(paths: Paths, plans: list[policy.Plan], config: dict[str, Any]) -> None:
    plan = _pick_plan(plans)
    if plan and config["plans"].pop(plan["instanceId"], None) is not None:
        store.save(paths.config, config)
        store.log(paths.events, "floor-removed", instance=plan["instanceId"])
        print(f"Removed every floor on {plan['name']}.")
    elif plan:
        print("That plan has no floor.")


def run(paths: Paths) -> None:
    while True:
        config = store.load(paths.config, store.DEFAULT_CONFIG)
        state = store.load(paths.state, store.DEFAULT_STATE)
        try:
            plans = supervisor.read_plans(paths)
        except Exception as error:  # noqa: BLE001 -- show the reason and keep the menu usable
            print(f"Could not read usage from T3 Code ({error}). Is T3 Code running?")
            plans = []
        _show(paths, plans, config, state)
        print(" 1  Set a floor        2  Remove a plan's floors     3  Refresh")
        print(" 4  Start supervisor   5  Stop supervisor            6  Start at sign-in on/off")
        grace = config.get("graceMinutes", 10)
        print(f" 7  Enforcement on/off (keeps floors)   8  Grace minutes (now {grace})   0  Exit")
        choice = _ask("> ")
        if choice == "0":
            return
        if choice == "1":
            _set_floor(paths, plans, config)
        elif choice == "2":
            _remove_floor(paths, plans, config)
        elif choice == "4":
            print(supervisor.start(paths))
        elif choice == "5":
            print(supervisor.stop(paths))
        elif choice == "6":
            print(system.set_autostart(not system.autostart_enabled()))
        elif choice == "7":
            config["enabled"] = not config.get("enabled", True)
            store.save(paths.config, config)
            print("Enforcement " + ("on." if config["enabled"] else "off. Floors are kept."))
        elif choice == "8":
            minutes = _ask("Minutes agents get to save their work before an interrupt: ")
            if minutes.isdigit():
                config["graceMinutes"] = int(minutes)
                store.save(paths.config, config)
