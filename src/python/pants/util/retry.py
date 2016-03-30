# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import time


logger = logging.getLogger(__name__)


def retry_on_exception(func, max_retries, exception_types, sleep_step=0):
  """Retry a callable against a set of exceptions, optionally sleeping between retries.

  :param callable func: The callable to retry.
  :param int max_retries: The maximum number of times to attempt running the function.
  :param tuple exception_types: The types of exceptions to catch for retry.
  :param float sleep_step: The unit of time to sleep, which is multiplied by the retry count (e.g.
                           a sleep step of .5 with 3 retries results in sleeps of [0, .5, 1].
                           Defaults to no sleeping between retries.
  """
  for i in range(0, max_retries):
    time.sleep(i * sleep_step)
    try:
      return func()
    except exception_types as e:
      logger.debug('encountered exception on retry #{}: {!r}'.format(i, e))
  raise
