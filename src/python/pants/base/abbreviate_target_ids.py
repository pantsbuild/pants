# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)


def abbreviate_target_ids(arr):
  """Map a list of target IDs to shortened versions.

  This method takes a list of strings (e.g. target IDs) and maps them to shortened versions of
  themselves.

  The original strings should consist of '.'-delimited segments, and the abbreviated versions are
  subsequences of these segments such that each string's subsequence is unique from others in @arr.

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

  :param arr: List of strings representing target IDs.
  """
  split_keys = [tuple(a.split('.')) for a in arr]

  split_keys_by_subseq = {}

  def subseq_map(arr, subseq_fn=None, result_cmp_fn=None):
    def subseq_map_rec(remaining_arr, subseq, indent=''):
      if not remaining_arr:
        if subseq_fn:
          subseq_fn(arr, subseq)
        return subseq

      next_segment = remaining_arr.pop()
      next_subseq = tuple([next_segment] + list(subseq))

      skip_value = subseq_map_rec(remaining_arr, subseq, indent + '\t')

      add_value = subseq_map_rec(remaining_arr, next_subseq, indent + '\t')

      remaining_arr.append(next_segment)

      if result_cmp_fn:
        if not subseq:
          # Empty subsequence should always lose.
          return add_value
        if result_cmp_fn(skip_value, add_value):
          return skip_value
        return add_value

      return None

    val = subseq_map_rec(list(arr), tuple())
    return val

  def add_subseq(arr, subseq):
    if subseq not in split_keys_by_subseq:
      split_keys_by_subseq[subseq] = set()
    if split_key not in split_keys_by_subseq[subseq]:
      split_keys_by_subseq[subseq].add(arr)

  for split_key in split_keys:
    subseq_map(split_key, add_subseq)

  def return_min_subseqs(subseq1, subseq2):
    collisions1 = split_keys_by_subseq[subseq1]
    collisions2 = split_keys_by_subseq[subseq2]
    return (len(collisions1) < len(collisions2)
            or (len(collisions1) == len(collisions2)
                and len(subseq1) <= len(subseq2)))

  min_subseq_by_key = {}

  for split_key in split_keys:
    min_subseq = subseq_map(split_key, result_cmp_fn=return_min_subseqs)
    if not min_subseq:
      raise Exception("No min subseq found for %s: %s" % (str(split_key), str(min_subseq)))
    min_subseq_by_key['.'.join(str(segment) for segment in split_key)] = '.'.join(min_subseq)

  return min_subseq_by_key
