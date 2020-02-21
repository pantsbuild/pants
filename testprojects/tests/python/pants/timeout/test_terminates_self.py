# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import signal
import time


def test_terminates_self():
    time.sleep(1)

    os.kill(os.getpid(), signal.SIGTERM)
