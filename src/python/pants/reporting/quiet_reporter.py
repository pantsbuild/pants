# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import sys
from dataclasses import dataclass

from colors import red

from pants.reporting.plaintext_reporter_base import PlainTextReporterBase
from pants.reporting.report import Report
from pants.reporting.reporter import Reporter


class QuietReporter(PlainTextReporterBase):
    """Squelched plaintext reporting, only prints errors and timing/cache stats (if requested)."""

    @dataclass(frozen=True)
    class Settings(Reporter.Settings):
        color: bool
        timing: bool
        cache_stats: bool

    def open(self):
        """Implementation of Reporter callback."""
        pass

    def close(self):
        """Implementation of Reporter callback."""
        self._emit(self.generate_epilog(self.settings))

    def start_workunit(self, workunit):
        """Implementation of Reporter callback."""
        pass

    def end_workunit(self, workunit):
        """Implementation of Reporter callback."""
        pass

    def do_handle_log(self, workunit, level, *msg_elements):
        """Implementation of Reporter callback."""
        # If the element is a (msg, detail) pair, we ignore the detail. There's no
        # useful way to display it on the console.
        elements = [e if isinstance(e, str) else e[0] for e in msg_elements]
        msg = "\n" + "".join(elements)
        if self.settings.color:
            msg = red(msg)
        self._emit(msg)

    def handle_output(self, workunit, label, s):
        """Implementation of Reporter callback."""
        pass

    def _emit(self, s):
        sys.stderr.write(s)

    def level_for_workunit(self, workunit, default_level):
        """Force the reporter to consider every workunit to be logging for level Report.ERROR."""
        return Report.ERROR
