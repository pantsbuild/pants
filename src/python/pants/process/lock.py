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
    return '{}.lock_message'.format(self.path)

  @property
  def missing_message_output(self):
    return (
      'Pid {} waiting for a file lock ({}), but there was no message at {} indicating who is holding it.'
      .format(os.getpid(), self.path, self.message_path)
    )

  def acquire(self, message_fn=print_to_stderr, **kwargs):
    logger.debug('acquiring lock: {!r}'.format(self))
    super().acquire(blocking=False)
    if not self.acquired:
      try:
        with open(self.message_path, 'rb') as f:
          message = f.read().decode('utf-8', 'replace')
          output = 'PID {} waiting for a file lock ({}) held by: {}'.format(os.getpid(), self.path, message)
      except IOError as e:
        if e.errno == errno.ENOENT:
          output = self.missing_message_output
        else:
          raise
      message_fn(output)
      super().acquire(**kwargs)

    if self.acquired:
      current_process = psutil.Process()
      message = '{} ({})'.format(current_process.pid, ' '.join(current_process.cmdline()))
      with open(self.message_path, 'wb') as f:
        f.write(message.encode())

    return self.acquired

  def release(self):
    logger.debug('releasing lock: {!r}'.format(self))
    if self.acquired:
      safe_delete(self.message_path)
    return super().release()
