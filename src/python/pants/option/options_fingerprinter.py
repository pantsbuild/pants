# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import functools
import json
import os
from hashlib import sha1

import six

from pants.base.build_environment import get_buildroot
from pants.base.hash_utils import stable_json_hash
from pants.option.custom_types import UnsetBool, dict_with_files_option, file_option, target_option


class Encoder(json.JSONEncoder):
  def default(self, o):
    if o is UnsetBool:
      return '_UNSET_BOOL_ENCODING'
    return super(Encoder, self).default(o)


stable_json_sha1 = functools.partial(stable_json_hash, encoder=Encoder)


class OptionsFingerprinter(object):
  """Handles fingerprinting options under a given build_graph.

  :API: public
  """

  @classmethod
  def combined_options_fingerprint_for_scope(cls, scope, options,
                                             build_graph=None, **kwargs):
    """Given options and a scope, compute a combined fingerprint for the scope.

    :param string scope: The scope to fingerprint.
    :param Options options: The `Options` object to fingerprint.
    :param BuildGraph build_graph: A `BuildGraph` instance, only needed if fingerprinting
                                   target options.
    :param dict **kwargs: Keyword parameters passed on to
                          `Options#get_fingerprintable_for_scope`.
    :return: Hexadecimal string representing the fingerprint for all `options`
             values in `scope`.
    """
    fingerprinter = cls(build_graph)
    hasher = sha1()
    pairs = options.get_fingerprintable_for_scope(scope, **kwargs)
    for (option_type, option_value) in pairs:
      hasher.update(
        # N.B. `OptionsFingerprinter.fingerprint()` can return `None`,
        # so we always cast to bytes here.
        six.binary_type(
          fingerprinter.fingerprint(option_type, option_value)
        )
      )
    return hasher.hexdigest()

  def __init__(self, build_graph=None):
    self._build_graph = build_graph

  def fingerprint(self, option_type, option_val):
    """Returns a hash of the given option_val based on the option_type.

    :API: public

    Returns None if option_val is None.
    """
    if option_val is None:
      return None

    # For simplicity, we always fingerprint a list.  For non-list-valued options,
    # this will be a singleton list.
    if not isinstance(option_val, (list, tuple)):
      option_val = [option_val]

    if option_type == target_option:
      return self._fingerprint_target_specs(option_val)
    elif option_type == file_option:
      return self._fingerprint_files(option_val)
    elif option_type == dict_with_files_option:
      return self._fingerprint_dict_with_files(option_val)
    else:
      return self._fingerprint_primitives(option_val)

  def _fingerprint_target_specs(self, specs):
    """Returns a fingerprint of the targets resolved from given target specs."""
    assert self._build_graph is not None, (
      'cannot fingerprint specs `{}` without a `BuildGraph`'.format(specs)
    )
    hasher = sha1()
    for spec in sorted(specs):
      for target in sorted(self._build_graph.resolve(spec)):
        # Not all targets have hashes; in particular, `Dependencies` targets don't.
        h = target.compute_invalidation_hash()
        if h:
          hasher.update(h)
    return hasher.hexdigest()

  def _assert_in_buildroot(self, filepath):
    """Raises an error if the given filepath isn't in the buildroot.

    Returns the normalized, absolute form of the path.
    """
    filepath = os.path.normpath(filepath)
    root = get_buildroot()
    if not os.path.abspath(filepath) == filepath:
      # If not absolute, assume relative to the build root.
      return os.path.join(root, filepath)
    else:
      if '..' in os.path.relpath(filepath, root).split(os.path.sep):
        # The path wasn't in the buildroot. This is an error because it violates the pants being
        # hermetic.
        raise ValueError('Received a file_option that was not inside the build root:\n'
                         '  file_option: {filepath}\n'
                         '  build_root:  {buildroot}\n'
                         .format(filepath=filepath, buildroot=root))
      return filepath

  def _fingerprint_files(self, filepaths):
    """Returns a fingerprint of the given filepaths and their contents.

    This assumes the files are small enough to be read into memory.
    """
    hasher = sha1()
    # Note that we don't sort the filepaths, as their order may have meaning.
    for filepath in filepaths:
      filepath = self._assert_in_buildroot(filepath)
      hasher.update(os.path.relpath(filepath, get_buildroot()))
      with open(filepath, 'rb') as f:
        hasher.update(f.read())
    return hasher.hexdigest()

  def _fingerprint_primitives(self, val):
    return stable_json_sha1(val)

  def _fingerprint_dict_with_files(self, option_val):
    """Returns a fingerprint of the given dictionary containing file paths.

    Any value which is a file path which exists on disk will be fingerprinted by that file's
    contents rather than by its path.

    This assumes the files are small enough to be read into memory.
    """
    # Dicts are wrapped in singleton lists. See the "For simplicity..." comment in `fingerprint()`.
    option_val = option_val[0]
    return stable_json_sha1({k: self._expand_possible_file_value(v) for k, v in option_val.items()})

  def _expand_possible_file_value(self, value):
    """If the value is a file, returns its contents. Otherwise return the original value."""
    if value and os.path.isfile(str(value)):
      with open(value, 'r') as f:
        return f.read()
    return value
