# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import json
from hashlib import sha1

from pants.option.options import Options
from pants.util.strutil import stable_json_sha1


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

    if option_type == Options.target_list:
      return self._fingerprint_target_specs(option_val)
    elif option_type == Options.file:
      return self._fingerprint_file(option_val)
    else:
      return self._fingerprint_primitive(option_val)

  def _fingerprint_target_specs(self, specs):
    """Returns a fingerprint of the targets resolved from given target specs."""
    targets = sorted(self._build_graph.resolve_specs(specs))
    hashes = (t.invalidation_hash() for t in targets)
    real_hashes = [h for h in hashes if h is not None]
    if not real_hashes:
      return None
    hasher = sha1()
    for h in real_hashes:
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
