# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.util.strutil import pluralize


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
  n = len(items)
  text = pluralize(n, item_type)
  if n == 0:
    return text
  else:
    detail = '\n'.join(str(x) for x in items)
    return text, detail
