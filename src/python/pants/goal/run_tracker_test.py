# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import datetime
import getpass
import re
import time

import pytest
from freezegun import freeze_time

from pants.base.build_environment import get_buildroot
from pants.base.exiter import PANTS_FAILED_EXIT_CODE, PANTS_SUCCEEDED_EXIT_CODE
from pants.goal.run_tracker import RunTracker
from pants.testutil.option_util import create_options_bootstrapper
from pants.util.contextutil import environment_as, temporary_dir
from pants.version import VERSION


@freeze_time(datetime.datetime(2020, 1, 1, 12, 0, 0), as_kwarg="frozen_time")
def test_run_tracker_timing_output(**kwargs) -> None:
    with temporary_dir() as buildroot:
        with environment_as(PANTS_BUILDROOT_OVERRIDE=buildroot):
            run_tracker = RunTracker(create_options_bootstrapper([]).bootstrap_options)
            run_tracker.start(run_start_time=time.time(), specs=["::"])
            frozen_time = kwargs["frozen_time"]
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
def test_run_information(exit_code, expected, **kwargs) -> None:
    with temporary_dir() as buildroot:
        with environment_as(PANTS_BUILDROOT_OVERRIDE=buildroot):
            run_tracker = RunTracker(create_options_bootstrapper([]).bootstrap_options)

            specs = ["src/python/pants/goal/run_tracker_test.py"]
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
            assert run_information["user"] == getpass.getuser()
            assert run_information["version"] == VERSION
            assert re.match("pants.*run_tracker_test.py", run_information["cmd_line"])
            assert run_information["specs_from_command_line"] == [
                "src/python/pants/goal/run_tracker_test.py"
            ]

            frozen_time = kwargs["frozen_time"]
            frozen_time.tick(delta=datetime.timedelta(seconds=1))

            run_tracker.end_run(exit_code)
            run_information_after_ended = run_tracker.run_information()
            assert run_information_after_ended["outcome"] == expected
