# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import datetime
import logging
import os
import sys
from builtins import object

from pants.util.dirutil import is_writable_dir, safe_open
from pants.util.memo import memoized_classproperty


logger = logging.getLogger(__name__)


class ExceptionSink(object):
  """A mutable singleton object representing where exceptions should be logged to."""

  @memoized_classproperty
  def instance(cls):
    return cls()

  def __init__(self, destination=None):
    # TODO: what assumptions can we make about the current directory of a process? Does it have to
    # exist / be readable / writable?
    if destination is None:
      destination = os.getcwd()
    self._destination = destination

  class ExceptionSinkError(Exception): pass

  def set_destination(self, dir_path):
    if not is_writable_dir(dir_path):
      # TODO: when this class sets up excepthooks, raising this should be safe, because we always
      # have a destination to log to (os.getcwd() if not otherwise set).
      raise self.ExceptionSinkError(
        "The provided exception sink path at '{}' is not a writable directory."
        .format(dir_path))
    self._destination = dir_path

  def get_destination(self):
    return self._destination

  def _exceptions_log_path(self):
    return os.path.join(self.get_destination(), 'logs', 'exceptions.log')

  def _iso_timestamp_for_now(self):
    return datetime.datetime.now().isoformat()

  # NB: This includes a trailing newline, but no leading newline.
  _EXCEPTION_LOG_FORMAT = """\
timestamp: {timestamp}
args: {args}
pid: {pid}
{message}
"""

  def _format_exception_message(self, msg):
    return self._EXCEPTION_LOG_FORMAT.format(
      timestamp=self._iso_timestamp_for_now(),
      args=sys.argv,
      pid=os.getpid(),
      message=msg,
    )

  def log_exception(self, msg):
    try:
      with safe_open(self._exceptions_log_path(), 'a') as exception_log:
        fatal_error_log_entry = self._format_exception_message(msg)
        exception_log.write(fatal_error_log_entry)
    except Exception as e:
      # TODO: If there is an error in writing to the exceptions log, we may want to consider trying
      # to write to another location (e.g. the cwd, if that is not already the destination).
      logger.error('Problem logging original exception: {}'.format(e))
