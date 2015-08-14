# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import json
from hashlib import sha1

from pants.option.custom_types import file_option, target_list_option


def stable_json_dumps(obj):
  return json.dumps(obj, ensure_ascii=True, allow_nan=False, sort_keys=True)


def stable_json_sha1(obj):
  return sha1(stable_json_dumps(obj)).hexdigest()


class OptionsFingerprinter(object):
  """Handles fingerprinting options under a given build_graph."""

  def __init__(self, build_graph):
    self._build_graph = build_graph

  def fingerprint(self, option_type, option_val):
    """Returns a hash of the given option_val based on the option_type.

    Returns None if option_val is None.
    """
    if option_val is None:
      return None

    if option_type == target_list_option:
      return self._fingerprint_target_specs(option_val)
    elif option_type == file_option:
      return self._fingerprint_file(option_val)
    else:
      return self._fingerprint_primitive(option_val)

  def _fingerprint_target_specs(self, specs):
    """Returns a fingerprint of the targets resolved from given target specs."""
    hasher = sha1()
    for spec in sorted(specs):
      for target in sorted(self._build_graph.resolve(spec)):
        # Not all targets have hashes; in particular, `Dependencies` targets don't.
        h = target.compute_invalidation_hash()
        if h:
          hasher.update(h)
    return hasher.hexdigest()

  def _fingerprint_file(self, filepath):
    """Returns a fingerprint of the given filepath and its contents."""
    hasher = sha1()
    hasher.update(filepath)
    with open(filepath, 'rb') as f:
      hasher.update(f.read())
    return hasher.hexdigest()

  def _fingerprint_primitive(self, val):
    return stable_json_sha1(val)
