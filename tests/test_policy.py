from datetime import UTC, datetime

from usage_floor import policy

NOW = 1_800_000_000.0


def plan(used: float, age: float = 60, window_id: str = "primary", checked: str | None = "auto") -> dict:
    checked_at = datetime.fromtimestamp(NOW - age, UTC).isoformat() if checked == "auto" else checked
    return {
        "instanceId": "codex",
        "name": "Personal",
        "plan": "ChatGPT Pro",
        "checkedAt": checked_at,
        "windows": [{"id": window_id, "label": "Weekly", "usedPercent": used, "resetsAt": "2027-01-01T00:00:00Z"}],
    }


RUN = {"runId": "r1", "threadId": "t1", "status": "running", "instanceId": "codex"}


def blocked(age: float) -> dict:
    return {"codex": {"since": NOW - age, "hits": []}}


class TestBreaches:
    def test_below_floor_breaches(self):
        hits = policy.breaches(plan(25), {"primary": 80}, NOW)
        assert [(h["remaining"], h["floor"]) for h in hits] == [(75.0, 80)]

    def test_at_or_above_floor_is_fine(self):
        assert policy.breaches(plan(20), {"primary": 80}, NOW) == []
        assert policy.breaches(plan(5), {"primary": 80}, NOW) == []

    def test_stale_reading_never_breaches(self):
        assert policy.breaches(plan(99, age=policy.STALE_SECONDS + 1), {"primary": 80}, NOW) == []

    def test_missing_reading_never_breaches(self):
        assert policy.breaches(plan(99, checked=None), {"primary": 80}, NOW) == []

    def test_unconfigured_window_is_ignored(self):
        assert policy.breaches(plan(99, window_id="five_hour"), {"primary": 80}, NOW) == []


class TestBlocked:
    def test_disabled_enforcement_blocks_nothing(self):
        config = {"enabled": False, "plans": {"codex": {"floors": {"primary": 80}}}}
        assert policy.compute_blocked(config, {}, {"codex": plan(50)}, NOW) == {}

    def test_block_keeps_its_start_time(self):
        config = {"enabled": True, "plans": {"codex": {"floors": {"primary": 80}}}}
        previous = {"codex": {"since": NOW - 500}}
        assert policy.compute_blocked(config, previous, {"codex": plan(50)}, NOW)["codex"]["since"] == NOW - 500

    def test_unknown_plan_is_skipped(self):
        config = {"enabled": True, "plans": {"gone": {"floors": {"primary": 80}}}}
        assert policy.compute_blocked(config, {}, {"codex": plan(50)}, NOW) == {}


class TestActions:
    def test_runs_present_when_block_begins_are_warned(self):
        assert policy.plan_actions([RUN], blocked(10), {}, 10, NOW) == [("warn", RUN)]

    def test_run_started_after_the_warning_is_interrupted(self):
        assert policy.plan_actions([RUN], blocked(3600), {}, 10, NOW) == [("interrupt", RUN)]

    def test_warned_run_is_interrupted_after_grace(self):
        threads = {"t1": {"runId": "r1", "warnedAt": NOW - 11 * 60}}
        assert policy.plan_actions([RUN], blocked(3600), threads, 10, NOW) == [("interrupt", RUN)]

    def test_warned_run_is_left_alone_within_grace(self):
        threads = {"t1": {"runId": "r1", "warnedAt": NOW - 60}}
        assert policy.plan_actions([RUN], blocked(3600), threads, 10, NOW) == []

    def test_other_plans_are_untouched(self):
        other = {**RUN, "instanceId": "claudeAgent"}
        assert policy.plan_actions([other], blocked(10), {}, 10, NOW) == []


class TestServerConfig:
    def test_parses_enabled_plans_and_skips_disabled(self):
        config = {"providers": [
            {"instanceId": "codex", "displayName": "Personal", "enabled": True, "status": "ready",
             "auth": {"label": "ChatGPT Pro"},
             "usageLimits": {"checkedAt": "2027-01-01T00:00:00Z",
                             "windows": [{"id": "primary", "label": "Gemini · Weekly", "usedPercent": 18},
                                         {"id": "broken", "usedPercent": None}]}},
            {"instanceId": "cursor", "enabled": False, "status": "disabled"},
        ]}
        plans = policy.plans_from_server_config(config)
        assert [p["instanceId"] for p in plans] == ["codex"]
        assert plans[0]["plan"] == "ChatGPT Pro"
        assert [w["label"] for w in plans[0]["windows"]] == ["Gemini - Weekly"]

    def test_warning_names_plan_window_and_floor(self):
        text = policy.warning_text(plan(25), policy.breaches(plan(25), {"primary": 80}, NOW), 10)
        assert "Personal (ChatGPT Pro)" in text
        assert "75.0% left (floor 80%)" in text
        assert "Within 10 minutes" in text
