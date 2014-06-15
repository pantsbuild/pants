# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)


def items_to_report_element(items, item_type):
  """Converts an iterable of items to a (message, detail) pair.

  - items: a list of items (e.g., Target instances) that can be str()-ed.
  - item_type: a string describing the type of item (e.g., 'target').

  Returns (message, detail) where message is the count of items (e.g., '26 targets')
  and detail is the text representation of the list of items, one per line.

  The return value can be used as an argument to Report.log().

  This is useful when we want to say "N targets" or "K sources"
  and allow the user to see which ones by clicking on that text.
  """
  def pluralize(x):
    if x.endswith('s'):
      return x + 'es'
    else:
      return x + 's'

  items = [str(x) for x in items]
  n = len(items)
  text = '%d %s' % (n, item_type if n == 1 else pluralize(item_type))
  if n == 0:
    return text
  else:
    detail = '\n'.join(items)
    return text, detail
