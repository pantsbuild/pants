# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
import sys
import time

from pants.base.exiter import PANTS_FAILED_EXIT_CODE
from pants.bin.pants_runner import PantsRunner
from pants.util.contextutil import maybe_profiled

TEST_STR = "T E S T"

logger = logging.getLogger(__name__)


def test():
    """An alternate testing entrypoint that helps avoid dependency linkages into `tests/python` from
    the `bin` target."""
    print(TEST_STR)


def test_env():
    """An alternate test entrypoint for exercising scrubbing."""
    import os

    print("PANTS_ENTRYPOINT={}".format(os.environ.get("PANTS_ENTRYPOINT")))


def main():
    with maybe_profiled(os.environ.get("PANTSC_PROFILE")):
        start_time = time.time()
        try:
            runner = PantsRunner(args=sys.argv, env=os.environ)
            exit_code = runner.run(start_time)
        except KeyboardInterrupt as e:
            print("Interrupted by user:\n{}".format(e), file=sys.stderr)
            exit_code = PANTS_FAILED_EXIT_CODE
        except Exception as e:
            logger.exception(e)
            exit_code = PANTS_FAILED_EXIT_CODE
    sys.exit(exit_code)
