# ==================================================================================================
# Copyright 2012 Twitter, Inc.
# --------------------------------------------------------------------------------------------------
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this work except in compliance with the License.
# You may obtain a copy of the License in the LICENSE file, or at:
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==================================================================================================

__author__ = 'Ryan Williams'

def abbreviate_target_ids(arr):
  """Map a list of target IDs to shortened versions.

  This method takes a list of strings (e.g. target IDs) and maps them to shortened versions of
  themselves.

  The original strings should consist of '.'-delimited segments, and the abbreviated versions are
  subsequences of these segments such that each string's subsequence is unique from others in @arr.

  For example: ::

     input: [
       'com.twitter.pants.a.b',
       'com.twitter.pants.a.c',
       'com.twitter.pants.d'
     ]

  might return: ::

     {
       'com.twitter.pants.a.b': 'b',
       'com.twitter.pants.a.c': 'c',
       'com.twitter.pants.d': 'd'
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

