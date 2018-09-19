# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import datetime
from builtins import object

from pants.util.dirutil import is_writable_dir


class ExceptionSink(object):
  """A mutable object representing where exceptions should be logged to."""

  def __init__(self):
    self._cached_destination = None

  class ExceptionSinkError(Exception): pass

  def _get_timestamp(self):
    return datetime.datetime.now().isoformat()

  def set_destination(self, dir_path):
    if not is_writable_dir(dir_path):
      raise self.ExceptionSinkError(
        "(at {}) The provided exception sink path at '{}' is not a writable directory."
        .format(self._get_timestamp(), dir_path))
    self._cached_destination = dir_path

  def get_destination(self):
    # TODO: check if the path is writable here too? Doing a syscall might be ok here, depending on
    # the usage pattern.
    if self._cached_destination is None:
      raise self.ExceptionSinkError(
        "(at {}) The exception sink path was not yet initialized with set_destination()."
        .format(self._get_timestamp()))
    return self._cached_destination
