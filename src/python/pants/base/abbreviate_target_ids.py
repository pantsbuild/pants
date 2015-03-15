# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from collections import Counter, defaultdict
from itertools import combinations


def abbreviate_target_ids(targets):
  """Map a list of target IDs to shortened versions.

  This method takes a list of strings (e.g. target IDs) and maps them to shortened versions of
  themselves.

  The original strings should consist of '.'-delimited segments, and the abbreviated versions are
  subsequences of these segments such that each string's subsequence is unique from others in @targets.

  For example: ::

     input: [
       'com.pants.a.b',
       'com.pants.a.c',
       'com.pants.d'
     ]

  might return: ::

     {
       'com.pants.a.b': 'b',
       'com.pants.a.c': 'c',
       'com.pants.d': 'd'
     }

  This can be useful for debugging purposes, removing a lot of boilerplate from printed lists of
  target IDs.

  :param targets: List of strings representing target IDs.
  """
  def subseqs(seq):
    return [ tuple(s) for n in range(len(seq) + 1) for s in combinations(seq, n) ]

  def abbreviation(parts, collisions):
    def cmp(s): return collisions[s], len(s)
    return '.'.join(min((s + (parts[-1],) for s in subseqs(parts[:-1])), key=cmp))

  split_targets = [ (t, t.split('.')) for t in targets ]
  collisions = Counter(s for _, split in split_targets for s in subseqs(split))

  return { t : abbreviation(s, collisions) for t, s in split_targets }
