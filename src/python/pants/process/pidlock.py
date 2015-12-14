# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import sys

import psutil
from lockfile import pidlockfile


logger = logging.getLogger(__name__)


class OwnerPrintingPIDLockFile(pidlockfile.PIDLockFile):
  def acquire(self, timeout=None):
    # If the lock is held, attempt to determine holder and print a message before waiting.
    # If owner process cannot be found, go ahead and kill the orphaned lock file before waiting.
    if self.is_locked():
      try:
        pid = self.read_pid()
        cmd = self.cmdline_for_pid(pid)
        if cmd is not None:
          print('Waiting on pants process {0} ({1}) to complete'.format(pid, cmd), file=sys.stderr)
        else:
          self.break_lock()
      except Exception as e:
        logger.warn('Error while determining lock owner: {0}'.format(e))

    return pidlockfile.PIDLockFile.acquire(self, timeout)

  @staticmethod
  def cmdline_for_pid(pid):
    try:
      process = psutil.Process(pid)
      return ' '.join(process.cmdline())
    except psutil.NoSuchProcess:
      return None
