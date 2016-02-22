# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import signal
import time


def test_ignores_terminate():
  def signal_term_handler(signal, frame):
    # Ignore SIGTERM.
    pass

  signal.signal(signal.SIGTERM, signal_term_handler)
  time.sleep(120)

  # We need a second sleep because the SIGTERM will interrupt the first sleep.
  time.sleep(120)
