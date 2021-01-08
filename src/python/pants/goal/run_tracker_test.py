# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import datetime
import time

from freezegun import freeze_time

from pants.base.exiter import PANTS_SUCCEEDED_EXIT_CODE
from pants.goal.run_tracker import RunTracker
from pants.testutil.option_util import create_options_bootstrapper


def test_run_tracker_timing_output() -> None:
    with freeze_time(datetime.datetime(2020, 1, 1, 12, 0, 0)) as frozen_time:
        open("BUILDROOT", "w")
        run_tracker = RunTracker(create_options_bootstrapper([]).bootstrap_options)
        run_tracker.start(run_start_time=time.time())
        frozen_time.tick(delta=datetime.timedelta(seconds=1))
        run_tracker.end_run(PANTS_SUCCEEDED_EXIT_CODE)

        timings = run_tracker.get_cumulative_timings()
        assert timings[0]["label"] == "main"
        assert timings[0]["timing"] == 1.0
