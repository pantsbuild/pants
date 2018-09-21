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


logger = logging.getLogger(__name__)


class ExceptionSink(object):
  """A mutable singleton object representing where exceptions should be logged to."""

  _destination = os.getcwd()

  def __new__(cls, *args, **kwargs):
    raise TypeError('Instances of {} are not allowed to be constructed!'
                    .format(cls.__name__))

  class ExceptionSinkError(Exception): pass

  @classmethod
  def set_destination(cls, dir_path):
    if not is_writable_dir(dir_path):
      # TODO: when this class sets up excepthooks, raising this should be safe, because we always
      # have a destination to log to (os.getcwd() if not otherwise set).
      raise cls.ExceptionSinkError(
        "The provided exception sink path at '{}' is not a writable directory."
        .format(dir_path))
    cls._destination = dir_path

  @classmethod
  def get_destination(cls):
    return cls._destination

  @classmethod
  def exceptions_log_path(cls, for_pid=None):
    intermediate_filename_component = '.{}'.format(for_pid) if for_pid else ''
    return os.path.join(
      cls.get_destination(),
      'logs',
      'exceptions{}.log'.format(intermediate_filename_component))

  @classmethod
  def _iso_timestamp_for_now(cls):
    return datetime.datetime.now().isoformat()

  # NB: This includes a trailing newline, but no leading newline.
  _EXCEPTION_LOG_FORMAT = """\
timestamp: {timestamp}
args: {args}
pid: {pid}
{message}
"""

  @classmethod
  def _format_exception_message(cls, msg, pid):
    return cls._EXCEPTION_LOG_FORMAT.format(
      timestamp=cls._iso_timestamp_for_now(),
      args=sys.argv,
      pid=pid,
      message=msg,
    )

  @classmethod
  def log_exception(cls, msg):
    try:
      pid = os.getpid()
      fatal_error_log_entry = cls._format_exception_message(msg, pid)
      # We care more about this log than the shared log, so completely write to it first. This
      # avoids any errors with concurrent modification of the shared log affecting the per-pid log.
      with safe_open(cls.exceptions_log_path(for_pid=pid), 'a') as pid_error_log:
        pid_error_log.write(fatal_error_log_entry)
      # TODO: we should probably guard this against concurrent modification somehow.
      with safe_open(cls.exceptions_log_path(), 'a') as shared_error_log:
        shared_error_log.write(fatal_error_log_entry)
    except Exception as e:
      # TODO: If there is an error in writing to the exceptions log, we may want to consider trying
      # to write to another location (e.g. the cwd, if that is not already the destination).
      logger.error('Problem logging original exception: {}'.format(e))
