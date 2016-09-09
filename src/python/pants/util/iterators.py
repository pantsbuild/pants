# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)


try:
  from itertools import accumulate  # Present in python3 stdlib.
except ImportError:
  import operator


  def accumulate(items, func=operator.add):
    """Reduce items yielding the initial item and then each reduced value after that.

    :param items: A possibly empty iterable.
    :param func: A binary operator that can combine items.
    :returns: An iterator over the first item if any and subsequent applications of `func` to the
              running "total".
    """
    iterator = iter(items)
    try:
      total = next(iterator)
    except StopIteration:
      return  # The items iterable is empty.`
    yield total
    for item in iterator:
      total = func(total, item)
      yield total
