# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

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
    super(OwnerPrintingInterProcessFileLock, self).acquire(blocking=False)
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
      super(OwnerPrintingInterProcessFileLock, self).acquire(**kwargs)

    if self.acquired:
      current_process = psutil.Process()
      message = '{} ({})'.format(current_process.pid, ' '.join(current_process.cmdline()))
      with open(self.message_path, 'wb') as f:
        f.write(message.encode('utf-8'))

    return self.acquired

  def release(self):
    if self.acquired:
      safe_delete(self.message_path)
    return super(OwnerPrintingInterProcessFileLock, self).release()
