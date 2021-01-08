# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import datetime
import json
import time
from pathlib import Path

from freezegun import freeze_time

from pants.base.exiter import PANTS_SUCCEEDED_EXIT_CODE
from pants.goal.run_tracker import RunTracker
from pants.testutil.option_util import create_options_bootstrapper
from pants.util.contextutil import temporary_dir


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


def test_stats_json_write() -> None:
    with freeze_time(datetime.datetime(2020, 1, 1, 12, 0, 0)) as frozen_time:
        with temporary_dir() as tmpdir:
            open("BUILDROOT", "w")
            json_file = Path(tmpdir) / "file.json"
            options = [f"--stats-json-file={json_file}"]
            run_tracker = RunTracker(create_options_bootstrapper(options).bootstrap_options)
            run_tracker.start(run_start_time=time.time())
            frozen_time.tick(delta=datetime.timedelta(seconds=1))
            run_tracker.end_run(PANTS_SUCCEEDED_EXIT_CODE)

            contents = open(json_file).read()
            json_contents = json.loads(contents)
            for key in ["run_info", "pantsd_stats", "cumulative_timings", "recorded_options"]:
                assert key in json_contents.keys()
