# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import code
import sys
import traceback
from contextlib import contextmanager

from pants.base.exception_sink import ExceptionSink


@contextmanager
def _interactive_console_excepthook():
    prev_excepthook = sys.excepthook
    sys.excepthook = ExceptionSink.original_excepthook
    try:
        yield
    finally:
        sys.excepthook = prev_excepthook


class InteractiveConsole:
    """A hacky way to spin up a repl anywhere inside of pants at any time!"""
    def interact(self, locals=None) -> None:
        console = code.InteractiveConsole(locals=locals)

        with _interactive_console_excepthook():
            exited_cleanly = False
            while not exited_cleanly:
                try:
                    console.interact()
                    exited_cleanly = True
                except Exception:
                    py_console.write(traceback.format_exc())
