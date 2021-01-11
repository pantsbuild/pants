# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import datetime
import time

from freezegun import freeze_time

from pants.base.exiter import PANTS_SUCCEEDED_EXIT_CODE
from pants.goal.run_tracker import RunTracker
from pants.testutil.option_util import create_options_bootstrapper
from pants.util.contextutil import environment_as, temporary_dir


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
