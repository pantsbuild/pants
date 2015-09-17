# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import sys
import threading


try:
    import thread
except ImportError:
    import _thread as thread


class Timeout:
    def __init__(self, seconds):
        self.timer = threading.Timer(seconds, self._handle_timeout)

    def _handle_timeout(self):
        sys.stderr.flush() # Python 3 stderr is likely buffered.
        thread.interrupt_main() # raises KeyboardInterrupt

    def __enter__(self):
        self.timer.start()

    def __exit__(self):
        self.timer.cancel()
