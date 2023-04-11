# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import datetime
import re
import time
from pathlib import Path

import pytest
from freezegun import freeze_time

from pants.base.build_environment import get_buildroot
from pants.base.exiter import PANTS_FAILED_EXIT_CODE, PANTS_SUCCEEDED_EXIT_CODE, ExitCode
from pants.goal.run_tracker import RunTracker
from pants.testutil.option_util import create_options_bootstrapper
from pants.util.contextutil import environment_as
from pants.util.osutil import getuser
from pants.version import VERSION


@freeze_time(datetime.datetime(2020, 1, 1, 12, 0, 0), as_kwarg="frozen_time")
def test_run_tracker_timing_output(tmp_path: Path, **kwargs) -> None:
    frozen_time = kwargs["frozen_time"]
    buildroot = tmp_path.as_posix()
    with environment_as(PANTS_BUILDROOT_OVERRIDE=buildroot):
        ob = create_options_bootstrapper([])
        run_tracker = RunTracker(ob.args, ob.bootstrap_options)
        run_tracker.start(run_start_time=time.time(), specs=["::"])
        frozen_time.tick(delta=datetime.timedelta(seconds=1))
        run_tracker.end_run(PANTS_SUCCEEDED_EXIT_CODE)

        timings = run_tracker.get_cumulative_timings()
        assert timings[0]["label"] == "main"
        assert timings[0]["timing"] == 1.0


@pytest.mark.parametrize(
    "exit_code,expected",
    [(PANTS_SUCCEEDED_EXIT_CODE, "SUCCESS"), (PANTS_FAILED_EXIT_CODE, "FAILURE")],
)
@freeze_time(datetime.datetime(2020, 1, 10, 12, 0, 1), as_kwarg="frozen_time")
def test_run_information(exit_code: ExitCode, expected: str, tmp_path: Path, **kwargs) -> None:
    frozen_time = kwargs["frozen_time"]
    buildroot = tmp_path.as_posix()
    with environment_as(PANTS_BUILDROOT_OVERRIDE=buildroot):
        spec = "test/example.py"
        ob = create_options_bootstrapper(["list", spec])
        run_tracker = RunTracker(ob.args, ob.bootstrap_options)

        specs = [spec]
        run_tracker.start(run_start_time=time.time(), specs=specs)

        run_information = run_tracker.run_information()
        assert run_information["buildroot"] == get_buildroot()
        assert run_information["path"] == get_buildroot()
        # freezegun doesn't seem to accurately mock the time zone,
        # (i.e. the time zone used depends on that of the machine that
        # executes the test), so we can only safely assert that the
        # month and year appear in the human-readable string contained
        # in the "datetime" key
        assert "Jan" in run_information["datetime"]
        assert "2020" in run_information["datetime"]
        assert run_information["timestamp"] == 1578657601.0
        assert run_information["user"] == getuser()
        assert run_information["version"] == VERSION
        assert re.match(f"pants.*{spec}", run_information["cmd_line"])
        assert run_information["specs_from_command_line"] == [spec]

        frozen_time.tick(delta=datetime.timedelta(seconds=1))
        run_tracker.end_run(exit_code)
        run_information_after_ended = run_tracker.run_information()
        assert run_information_after_ended["outcome"] == expected


@freeze_time(datetime.datetime(2020, 1, 10, 12, 0, 1), as_kwarg="frozen_time")
def test_anonymous_telemetry(monkeypatch, tmp_path: Path, **kwargs) -> None:
    frozen_time = kwargs["frozen_time"]
    buildroot = tmp_path.as_posix()
    with environment_as(PANTS_BUILDROOT_OVERRIDE=buildroot):
        ob = create_options_bootstrapper([])
        opts = ob.bootstrap_options
        monkeypatch.setattr(opts, "_goals", ["test", "customgoal", "lint"])
        run_tracker = RunTracker(ob.args, opts)
        run_tracker.start(run_start_time=time.time(), specs=[])
        frozen_time.tick(delta=datetime.timedelta(seconds=1))
        run_tracker.end_run(PANTS_SUCCEEDED_EXIT_CODE)
        repo_id = "A" * 36
        telemetry = run_tracker.get_anonymous_telemetry_data(repo_id)

        # Check that all keys have non-trivial values.
        for key in (
            "run_id",
            "timestamp",
            "duration",
            "outcome",
            "platform",
            "python_implementation",
            "python_version",
            "pants_version",
            "repo_id",
            "machine_id",
            "user_id",
            "standard_goals",
            "num_goals",
        ):
            assert bool(telemetry.get(key))

        # Verify a few easy-to-check values.
        assert telemetry["timestamp"] == "1578657601.0"
        assert telemetry["duration"] == "1.0"
        assert telemetry["outcome"] == "SUCCESS"
        assert telemetry["standard_goals"] == ["test", "lint"]
        assert telemetry["num_goals"] == "3"


def test_anonymous_telemetry_with_no_repo_id(tmp_path: Path) -> None:
    buildroot = tmp_path.as_posix()
    with environment_as(PANTS_BUILDROOT_OVERRIDE=buildroot):
        ob = create_options_bootstrapper([])
        run_tracker = RunTracker(ob.args, ob.bootstrap_options)
        run_tracker.start(run_start_time=time.time(), specs=[])
        run_tracker.end_run(PANTS_SUCCEEDED_EXIT_CODE)
        repo_id = ""
        telemetry = run_tracker.get_anonymous_telemetry_data(repo_id)

        # Check that these keys have non-trivial values.
        for key in (
            "run_id",
            "timestamp",
            "duration",
            "outcome",
            "platform",
            "python_implementation",
            "python_version",
            "pants_version",
        ):
            assert bool(telemetry.get(key))

        for key in ("repo_id", "machine_id", "user_id"):
            assert telemetry.get(key) == ""
