# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import time


logger = logging.getLogger(__name__)


def retry_on_exception(func, max_retries, exception_types, backoff_func=lambda n: 0):
  """Retry a callable against a set of exceptions, optionally sleeping between retries.

  :param callable func: The callable to retry.
  :param int max_retries: The maximum number of times to attempt running the function.
  :param tuple exception_types: The types of exceptions to catch for retry.
  :param callable backoff_func: A callable that will be called with the current attempt count to
                                determine the amount of time to sleep between retries. E.g. a
                                max_retries=4 with a backoff_func=lambda n: n * n will result in
                                sleeps of [1, 4, 9] between retries. Defaults to no backoff.
  """
  for i in range(0, max_retries):
    if i:
      time.sleep(backoff_func(i))
    try:
      return func()
    except exception_types as e:
      logger.debug('encountered exception on retry #{}: {!r}'.format(i, e))
  raise
