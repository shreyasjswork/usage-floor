"""The supervisor loop: read usage, compare it with the floors, and park or resume agents."""

from __future__ import annotations

import contextlib
import json
import os
import time
from typing import Any

from usage_floor import policy, store, system
from usage_floor.paths import Paths
from usage_floor.t3 import T3Client, T3Error, active_runs


def read_plans(paths: Paths) -> list[policy.Plan]:
    with T3Client(paths) as client:
        return policy.plans_from_server_config(client.server_config())


def _apply(client: T3Client, paths: Paths, *, kind: str, run: policy.Run, entry: dict[str, Any], text: str) -> None:
    if kind == "warn":
        client.steer(run["threadId"], run["runId"], text)
        entry["warnedAt"] = time.time()
    else:
        client.interrupt(run["threadId"], run["runId"], policy.INTERRUPT_REASON)
        entry["interruptedAt"] = time.time()
    store.log(paths.events, kind, thread=run["threadId"], run=run["runId"], instance=run["instanceId"])


def _resume(client: T3Client, paths: Paths, threads: dict[str, Any], lifted: set[str], enabled: bool) -> None:
    store.log(paths.events, "floor-lifted", instances=sorted(lifted))
    for thread, entry in list(threads.items()):
        if entry.get("instanceId") not in lifted:
            continue
        if enabled and (entry.get("interruptedAt") or entry.get("warnedAt")):
            try:
                client.resume_queue(thread)
                client.queue_message(thread, policy.RESUME_TEXT)
                store.log(paths.events, "resume", thread=thread)
            except (OSError, T3Error) as error:
                store.log(paths.events, "action-failed", kind="resume", thread=thread, error=str(error)[:500])
        threads.pop(thread, None)


def poll(paths: Paths, dry_run: bool = False) -> dict[str, Any]:
    """One supervisor pass. With `dry_run`, report the decisions without acting or saving."""
    config = store.load(paths.config, store.DEFAULT_CONFIG)
    state = store.load(paths.state, store.DEFAULT_STATE)
    plans = {plan["instanceId"]: plan for plan in read_plans(paths)}
    blocked = policy.compute_blocked(config, state["blocked"], plans)
    lifted = set(state["blocked"]) - set(blocked)
    grace = int(config.get("graceMinutes", 10))
    actions = policy.plan_actions(active_runs(paths.t3_state_db), blocked, state["threads"], grace)
    decided = [(kind, run["threadId"]) for kind, run in actions]
    summary = {"blocked": blocked, "lifted": sorted(lifted), "actions": decided}
    if dry_run:
        return summary
    for instance in set(blocked) - set(state["blocked"]):
        store.log(paths.events, "floor-reached", instance=instance, hits=blocked[instance]["hits"])
    if actions or lifted:
        with T3Client(paths) as client:
            for kind, run in actions:
                entry = state["threads"].setdefault(run["threadId"], {"instanceId": run["instanceId"]})
                entry["runId"] = run["runId"]
                text = policy.warning_text(plans[run["instanceId"]], blocked[run["instanceId"]]["hits"], grace)
                try:
                    _apply(client, paths, kind=kind, run=run, entry=entry, text=text)
                except (OSError, T3Error) as error:
                    store.log(paths.events, "action-failed", kind=kind, thread=run["threadId"], error=str(error)[:500])
            if lifted:
                _resume(client, paths, state["threads"], lifted, config.get("resumeOnLift", True))
    state["blocked"] = blocked
    state["lastPoll"] = store.iso()
    store.save(paths.state, state)
    return summary


# -- background process ------------------------------------------------------------------------

def running_pid(paths: Paths) -> int | None:
    try:
        pid = json.loads(paths.lock.read_text(encoding="utf-8"))["pid"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return pid if isinstance(pid, int) and system.pid_alive(pid) else None


def run_forever(paths: Paths) -> None:
    if running_pid(paths):
        return
    paths.home.mkdir(parents=True, exist_ok=True)
    paths.lock.write_text(json.dumps({"pid": os.getpid(), "started": store.iso()}), encoding="utf-8")
    store.log(paths.events, "supervisor-start", pid=os.getpid())
    try:
        while True:
            try:
                poll(paths)
            except Exception as error:  # noqa: BLE001 -- T3 may be restarting; try again next pass
                store.log(paths.events, "poll-failed", error=str(error)[:500])
            time.sleep(policy.POLL_SECONDS)
    finally:
        with contextlib.suppress(OSError, ValueError):
            if json.loads(paths.lock.read_text(encoding="utf-8")).get("pid") == os.getpid():
                paths.lock.unlink()


def start(paths: Paths) -> str:
    if running_pid(paths):
        return "The supervisor is already running."
    system.spawn_supervisor()
    for _ in range(20):
        time.sleep(0.25)
        if running_pid(paths):
            return "Supervisor started."
    return "Supervisor launched; it shows as running within a few seconds."


def stop(paths: Paths) -> str:
    pid = running_pid(paths)
    if not pid:
        return "The supervisor is not running."
    system.terminate(pid)
    with contextlib.suppress(OSError):
        paths.lock.unlink()
    store.log(paths.events, "supervisor-stop", pid=pid)
    return "Supervisor stopped."
