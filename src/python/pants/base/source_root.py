# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os

from twitter.common.collections import OrderedSet

from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TargetDefinitionException


class SourceRoot(object):
  """Allows registration of a source root for a set of targets.

  A source root is the base path sources for a particular language are found relative to.
  Generally compilers or interpreters for the source will expect sources relative to a base path
  and a source root allows calculation of the correct relative paths.

  E.g., a Java compiler probably expects to find ``.java`` files for
  ``package com.twitter.common.net`` in ``*something*/com/twitter/common/net``.
  The ``source_root`` command specifies that *something*.

  It is illegal to have nested source roots.
  """
  _ROOTS_BY_TYPE = {}
  _TYPES_BY_ROOT = {}
  _SEARCHED = set()

  def __init__(self, parse_context):
    self.rel_path = parse_context.rel_path

  def __call__(self, basedir, *allowed_target_types):
    allowed_target_types = [proxy._target_type for proxy in allowed_target_types]
    SourceRoot.register(os.path.join(self.rel_path, basedir), *allowed_target_types)

  def here(self, *allowed_target_types):
    """Registers the cwd as a source root for the given target types."""
    allowed_target_types = [proxy._target_type for proxy in allowed_target_types]
    SourceRoot.register(self.rel_path, *allowed_target_types)

  @classmethod
  def reset(cls):
    """Reset all source roots to empty. Only intended for testing."""
    cls._ROOTS_BY_TYPE = {}
    cls._TYPES_BY_ROOT = {}
    cls._SEARCHED = set()

  @classmethod
  def find(cls, target):
    """Finds the source root for the given target.

    If none is registered, returns the parent directory of the target's BUILD file.
    """

    target_path = target.address.spec_path

    def _find():
      for root_dir, types in cls._TYPES_BY_ROOT.items():
        if target_path.startswith(root_dir):  # The only candidate root for this target.
          # Validate the target type, if restrictions were specified.
          if types and not isinstance(target, tuple(types)):
            # TODO: Find a way to use the BUILD file aliases in the error message, instead
            # of target.__class__.__name__. E.g., java_tests instead of JavaTests.
            raise TargetDefinitionException(target,
                'Target type %s not allowed under %s' % (target.__class__.__name__, root_dir))
          return root_dir
      return None

    # Try already registered roots
    root = _find()
    if root:
      return root

    # Finally, resolve files relative to the BUILD file parent dir as the target base
    return target_path

  @classmethod
  def types(cls, root):
    """Returns the set of target types rooted at root."""
    return cls._TYPES_BY_ROOT[root]

  @classmethod
  def roots(cls, target_type):
    """Returns the set of roots for given target type."""
    return cls._ROOTS_BY_TYPE[target_type]

  @classmethod
  def all_roots(cls):
    """Returns a mapping from source roots to the associated target types."""
    return dict(cls._TYPES_BY_ROOT)

  @classmethod
  def register(cls, basedir, *allowed_target_types):
    """Registers the given basedir (relative to the buildroot) as a source root.

    :param string basedir: The base directory to resolve sources relative to.
    :param list allowed_target_types: Optional list of target types. If specified, we enforce that
      only targets of those types appear under this source root.
    """
    cls._register(basedir, *allowed_target_types)

  @classmethod
  def _register(cls, source_root_dir, *allowed_target_types):
    """Registers a source root.

    :source_root_dir The source root directory against which we resolve source paths,
                     relative to the build root.
    :allowed_target_types Optional list of target types. If specified, we enforce that
                          only targets of those types appear under this source root.
    """
    # Verify that source_root_dir doesn't reach outside buildroot.
    buildroot = os.path.normpath(get_buildroot())
    if source_root_dir.startswith(buildroot):
      abspath = os.path.normpath(source_root_dir)
    else:
      abspath = os.path.normpath(os.path.join(buildroot, source_root_dir))
    if not abspath.startswith(buildroot):
      raise ValueError('Source root %s is not under the build root %s' % (abspath, buildroot))
    source_root_dir = os.path.relpath(abspath, buildroot)

    types = cls._TYPES_BY_ROOT.get(source_root_dir)
    if types is None:
      types = OrderedSet()
      cls._TYPES_BY_ROOT[source_root_dir] = types

    for allowed_target_type in allowed_target_types:
      types.add(allowed_target_type)
      roots = cls._ROOTS_BY_TYPE.get(allowed_target_type)
      if roots is None:
        roots = OrderedSet()
        cls._ROOTS_BY_TYPE[allowed_target_type] = roots
      roots.add(source_root_dir)
