# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from hashlib import sha1

from pants.option.options import Options


class OptionsFingerprinter(object):
  """Handles fingerprinting options under a given context."""

  def __init__(self, context):
    self._context = context

  def fingerprint(self, option_type, option_val):
    """Returns a hash of the given option_val based on the option_type.

    Returns None if option_val is None.
    """
    if option_val is None:
      return None

    if option_type == Options.dict:
      return self._fingerprint_dict(option_val)
    elif option_type == Options.list:
      return self._fingerprint_list(option_val)
    elif option_type == Options.target_list:
      return self._fingerprint_target_specs(option_val)
    elif option_type == Options.file:
      return self._fingerprint_file(option_val)
    else:
      return self._fingerprint_primitive(option_val)

  def _fingerprint_dict(self, d):
    return self._hash(frozenset(d.items()))

  def _fingerprint_list(self, l):
    return self._hash(frozenset(l))

  def _fingerprint_target_specs(self, specs):
    """Returns a fingerprint of the targets resolved from given target specs."""
    hasher = sha1()
    for spec in sorted(specs):
      for target in sorted(self._context.resolve(spec)):
        hasher.update(target.compute_invalidation_hash())
    return hasher.hexdigest()

  def _fingerprint_file(self, filepath):
    """Returns a fingerprint of the given filepath and its contents."""
    hasher = sha1()
    hasher.update(filepath)
    with open(filepath, 'rb') as f:
      hasher.update(f.read())
    return hasher.hexdigest()

  def _fingerprint_primitive(self, val):
    return self._hash(val)

  def _hash(self, val):
    return sha1(str(hash(val))).hexdigest()
