import json
import multiprocessing
import os
from pathlib import Path

import pytest

import waytimer


def test_pause_resume_excludes_pause(monkeypatch, tmp_path):
    timer = waytimer.ActivityTimer(tmp_path)
    clock = iter([100.0, 101.0, 105.0, 108.0, 120.0])
    monkeypatch.setattr(waytimer.time, "time", lambda: next(clock))
    mono = iter([10.0, 11.0, 15.0, 18.0, 20.0])
    monkeypatch.setattr(waytimer.time, "monotonic", lambda: next(mono))

    assert timer.create_activity("focus")
    assert timer.pause_activity()
    assert timer.current_activity["paused_at"] == 101.0
    assert timer._get_elapsed_time(timer.current_activity) == pytest.approx(1.0)

    assert timer.pause_activity()
    assert timer.current_activity["paused_at"] is None
    assert timer._get_elapsed_time(timer.current_activity) == pytest.approx(4.0)


def test_corrupt_json_is_backed_up_and_reset(tmp_path):
    (tmp_path / "activities.json").write_text("{bad json", encoding="utf-8")
    (tmp_path / "current.json").write_text("not json", encoding="utf-8")

    timer = waytimer.ActivityTimer(tmp_path)

    assert timer.activities == {}
    assert timer.current_activity is None
    backups = list(tmp_path.glob("*.corrupt-*.bak"))
    assert len(backups) == 2
    assert any("{bad json" in backup.read_text(encoding="utf-8") for backup in backups)


def test_atomic_persistence_replaces_files(monkeypatch, tmp_path):
    timer = waytimer.ActivityTimer(tmp_path)
    original_replace = waytimer.os.replace
    replacements = []

    def tracking_replace(source, destination):
        replacements.append((Path(source), Path(destination)))
        return original_replace(source, destination)

    monkeypatch.setattr(waytimer.os, "replace", tracking_replace)
    timer.activities["reading"] = {"name": "reading", "total_time": 12.0, "sessions": []}
    timer._save_activities()

    assert json.loads(timer.data_file.read_text(encoding="utf-8"))["reading"]["total_time"] == 12.0
    assert replacements
    assert replacements[-1][1] == timer.data_file
    assert not list(tmp_path.glob(".activities.json.*"))


def _concurrent_create(data_dir, name):
    timer = waytimer.ActivityTimer(data_dir)
    timer.create_activity(name)


def test_concurrent_invocations_are_locked(tmp_path):
    if waytimer.fcntl is None:
        pytest.skip("fcntl unavailable")

    processes = [
        multiprocessing.Process(target=_concurrent_create, args=(tmp_path, f"activity-{i}"))
        for i in range(4)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(10)
        assert process.exitcode == 0

    activities = json.loads((tmp_path / "activities.json").read_text(encoding="utf-8"))
    assert len(activities) == 4
