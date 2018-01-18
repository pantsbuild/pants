# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import threading
from collections import namedtuple


DEFAULT_LOG_PATH = '/tmp/pants_debug.log'


def dlog(msg, log_path=DEFAULT_LOG_PATH):
  """A handy log utility for debugging multi-process, multi-threaded activities."""
  with open(log_path, 'ab') as f:
    f.write('\n{}@{}: {}'.format(os.getpid(), threading.current_thread().name, msg))


class ProxyLogger(namedtuple('ProxyLogger', ['wrapped_object', 'log_path'])):
  """An instance-wrapping method call logger that uses `dlog` logging.

  Example usage:

    >>> import sys
    >>> from pants.util.debug import ProxyLogger
    >>> sys.stdout = ProxyLogger.wrap_object(sys.stdout)
    >>> sys.stdout.write('blah\n')
    blah
    >>>

  results in logging in `/tmp/pants_debug.log` like:

  ...
  32912@MainThread: <open file '<stdout>', mode 'w' at 0x1047150>.write(*('blah\n',), **{}) -> None
  ...

  """

  @classmethod
  def wrap_object(cls, obj, log_path=DEFAULT_LOG_PATH):
    return cls(obj, log_path)

  def __getattr__(self, attr):
    def wrapped_method_call(*args, **kwargs):
      r = getattr(self.wrapped_object, attr)(*args, **kwargs)
      dlog(
        '{}.{}(*{}, **{}) -> {}'.format(self.wrapped_object, attr, args, kwargs, r),
        self.log_path
      )
      return r
    return wrapped_method_call
