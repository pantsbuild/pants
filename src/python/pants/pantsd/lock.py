# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import errno
import logging
import os
import sys

import psutil
from fasteners import InterProcessLock

from pants.util.dirutil import safe_delete

logger = logging.getLogger(__name__)


def print_to_stderr(message):
    print(message, file=sys.stderr)


class OwnerPrintingInterProcessFileLock(InterProcessLock):
    @property
    def message_path(self):
        return f"{self.path_str}.lock_message"

    @property
    def path_str(self):
        return self.path.decode()

    @property
    def missing_message_output(self):
        return f"Pid {os.getpid()} waiting for a file lock ({self.path_str}), but there was no message at {self.message_path} indicating who is holding it."

    def acquire(self, message_fn=print_to_stderr, **kwargs):
        logger.debug(f"acquiring lock: {self!r}")
        super().acquire(blocking=False)
        if not self.acquired:
            try:
                with open(self.message_path, "rb") as f:
                    message = f.read().decode("utf-8", "replace")
                    output = f"PID {os.getpid()} waiting for a file lock ({self.path_str}) held by: {message}"
            except OSError as e:
                if e.errno == errno.ENOENT:
                    output = self.missing_message_output
                else:
                    raise
            message_fn(output)
            super().acquire(**kwargs)

        if self.acquired:
            current_process = psutil.Process()
            cmd_line = " ".join(current_process.cmdline())
            message = f"{current_process.pid} ({cmd_line})"
            with open(self.message_path, "wb") as f:
                f.write(message.encode())

        return self.acquired

    def release(self):
        logger.debug(f"releasing lock: {self!r}")
        if self.acquired:
            safe_delete(self.message_path)
        return super().release()
