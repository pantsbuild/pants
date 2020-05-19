# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import sys

from pants.reporting.report import Report


class MockLogger:
    """A standalone logger that writes to stderr.

    :API: public

    Useful for testing without requiring the full RunTracker reporting framework.
    """

    def __init__(self, level=Report.INFO):
        self._level = level

    def _maybe_log(self, level, *msg_elements):
        if level <= self._level:
            sys.stderr.write("".join(msg_elements))

    def debug(self, *msg_elements):
        """
        :API: public
        """
        self._maybe_log(Report.DEBUG, *msg_elements)

    def info(self, *msg_elements):
        """
        :API: public
        """
        self._maybe_log(Report.INFO, *msg_elements)

    def warn(self, *msg_elements):
        """
        :API: public
        """
        self._maybe_log(Report.WARN, *msg_elements)

    def error(self, *msg_elements):
        """
        :API: public
        """
        self._maybe_log(Report.ERROR, *msg_elements)
