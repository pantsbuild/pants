# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import time

from pants.base.exception_sink import ExceptionSink
from pants.bin.pants_runner import PantsRunner
from pants.util.contextutil import maybe_profiled

TEST_STR = "T E S T"


def test():
    """An alternate testing entrypoint that helps avoid dependency linkages into `tests/python` from
    the `bin` target."""
    print(TEST_STR)


def test_env():
    """An alternate test entrypoint for exercising scrubbing."""
    import os

    print("PANTS_ENTRYPOINT={}".format(os.environ.get("PANTS_ENTRYPOINT")))


def main():
    start_time = time.time()

    with maybe_profiled(os.environ.get("PANTSC_PROFILE")):
        try:
            PantsRunner(start_time=start_time).run()
        except KeyboardInterrupt as e:
            ExceptionSink.get_global_exiter().exit_and_fail("Interrupted by user:\n{}".format(e))
