"""Pure decision logic: which plans are below their floor and what to do about each run.

Nothing here talks to T3 or the disk, so every rule is covered by plain unit tests.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

POLL_SECONDS = 120
STALE_SECONDS = 20 * 60

Plan = dict[str, Any]
Run = dict[str, Any]


def plans_from_server_config(config: dict[str, Any]) -> list[Plan]:
    """Enabled T3 provider instances with their plan label and usage windows."""
    plans: list[Plan] = []
    for provider in config.get("providers", []):
        if not provider.get("enabled") or provider.get("status") == "disabled":
            continue
        limits = provider.get("usageLimits") or {}
        auth = provider.get("auth") or {}
        windows = [
            {**w, "label": str(w.get("label") or w.get("id")).replace("·", "-")}
            for w in limits.get("windows", [])
            if isinstance(w.get("usedPercent"), (int, float))
        ]
        plans.append({
            "instanceId": provider.get("instanceId"),
            "name": provider.get("displayName") or provider.get("instanceId"),
            "plan": auth.get("label") or auth.get("type") or "",
            "checkedAt": limits.get("checkedAt"),
            "windows": windows,
        })
    return plans


def reading_age(plan: Plan, now: float | None = None) -> float | None:
    """Seconds since T3 last read this plan's usage, or None when unknown."""
    try:
        checked = datetime.fromisoformat(plan["checkedAt"]).timestamp()
    except (KeyError, TypeError, ValueError):
        return None
    return (time.time() if now is None else now) - checked


def breaches(plan: Plan, floors: dict[str, float], now: float | None = None) -> list[dict[str, Any]]:
    """Windows whose unused share is below the configured floor. Stale or missing data never breaches."""
    age = reading_age(plan, now)
    if age is None or age > STALE_SECONDS:
        return []
    hits = []
    for window in plan["windows"]:
        floor = floors.get(window.get("id"))
        if floor is None:
            continue
        remaining = round(100 - float(window["usedPercent"]), 1)
        if remaining < floor:
            hits.append({
                "window": window.get("label") or window.get("id"),
                "remaining": remaining,
                "floor": floor,
                "resetsAt": window.get("resetsAt"),
            })
    return hits


def compute_blocked(config: dict[str, Any], previous: dict[str, Any], plans: dict[str, Plan],
                    now: float | None = None) -> dict[str, Any]:
    """Plans currently below a floor, keeping the time each block began."""
    if not config.get("enabled", True):
        return {}
    moment = time.time() if now is None else now
    blocked = {}
    for instance, entry in config.get("plans", {}).items():
        hits = breaches(plans[instance], entry.get("floors", {}), moment) if instance in plans else []
        if hits:
            blocked[instance] = {"since": previous.get(instance, {}).get("since", moment), "hits": hits}
    return blocked


def plan_actions(runs: list[Run], blocked: dict[str, Any], threads: dict[str, Any], grace_minutes: int,
                 now: float | None = None) -> list[tuple[str, Run]]:
    """Decide per run: `warn` runs found when a block begins, `interrupt` them after the grace period,
    and `interrupt` any run that starts on a blocked plan after the warning went out."""
    moment = time.time() if now is None else now
    actions: list[tuple[str, Run]] = []
    for run in runs:
        block = blocked.get(run["instanceId"])
        if not block:
            continue
        seen = threads.get(run["threadId"], {})
        if seen.get("runId") != run["runId"]:
            started_late = bool(seen) or moment - block["since"] > POLL_SECONDS * 1.5
            actions.append(("interrupt" if started_late else "warn", run))
        elif (seen.get("warnedAt") and not seen.get("interruptedAt")
              and moment - seen["warnedAt"] > grace_minutes * 60):
            actions.append(("interrupt", run))
    return actions


def warning_text(plan: Plan, hits: list[dict[str, Any]], grace_minutes: int) -> str:
    detail = "; ".join(f"{h['window']} {h['remaining']}% left (floor {h['floor']:g}%)" for h in hits)
    return (
        f"Usage floor reached for {plan['name']} ({plan['plan']}): {detail}. "
        f"Stop starting new work on this plan. Within {grace_minutes} minutes: commit or save your current "
        "state, write a short handoff of what remains (files, next step), and end this turn. "
        "Do not launch new agents on this plan; Usage Floor resumes this thread when the floor lifts."
    )


RESUME_TEXT = "Usage floor lifted for this plan. Resume your previous work from your handoff."
INTERRUPT_REASON = "Usage floor reached for this plan"
