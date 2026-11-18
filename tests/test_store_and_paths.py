import json

from usage_floor import paths, store


def test_missing_file_yields_a_copy_of_the_default(tmp_path):
    value = store.load(tmp_path / "missing.json", store.DEFAULT_CONFIG)
    value["plans"]["x"] = {}
    assert store.DEFAULT_CONFIG["plans"] == {}


def test_broken_file_yields_the_default(tmp_path):
    target = tmp_path / "config.json"
    target.write_text("{not json", encoding="utf-8")
    assert store.load(target, store.DEFAULT_CONFIG) == store.DEFAULT_CONFIG


def test_save_round_trips_and_fills_new_keys(tmp_path):
    target = tmp_path / "nested" / "config.json"
    store.save(target, {"plans": {"codex": {"floors": {"primary": 80}}}})
    loaded = store.load(target, store.DEFAULT_CONFIG)
    assert loaded["plans"]["codex"]["floors"]["primary"] == 80
    assert loaded["graceMinutes"] == 10


def test_log_appends_json_lines(tmp_path):
    target = tmp_path / "events.jsonl"
    store.log(target, "floor-set", floor=80)
    store.log(target, "floor-removed")
    events = [json.loads(line)["event"] for line in target.read_text(encoding="utf-8").splitlines()]
    assert events == ["floor-set", "floor-removed"]


def test_environment_overrides_every_location(monkeypatch, tmp_path):
    monkeypatch.setenv("USAGE_FLOOR_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("USAGE_FLOOR_T3_HOME", str(tmp_path / "t3"))
    monkeypatch.setenv("USAGE_FLOOR_T3_CLI", "custom-t3")
    resolved = paths.resolve()
    assert resolved.config == tmp_path / "data" / "config.json"
    assert resolved.t3_state_db == tmp_path / "t3" / "userdata" / "statev2.sqlite"
    assert resolved.t3_cli == "custom-t3"
