# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)


def combined_dict(*dicts):
  """Combine one or more dicts into a new, unified dict (dicts to the right take precedence)."""
  return {k: v for d in dicts for k, v in d.items()}

def recursively_update(dict, dict2):
  """dict.update but which merges child dicts (dict2 takes precedence where there's conflict)."""
  for k, v in dict2.iteritems():
    if k in dict:
      if isinstance(v, type(dict)):
        recursively_update(dict[k], v)
        continue
    dict[k] = v
