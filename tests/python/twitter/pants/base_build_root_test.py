# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
import unittest
from tempfile import mkdtemp

from twitter.common.dirutil import safe_mkdir, safe_open, safe_rmtree

from pants.base.address import Address
from pants.base.build_root import BuildRoot
from pants.base.target import Target
from pants.targets.sources import SourceRoot


class BaseBuildRootTest(unittest.TestCase):
  """A baseclass useful for tests requiring a temporary buildroot."""

  build_root = None

  @classmethod
  def build_path(cls, relpath):
    """Returns the canonical BUILD file path for the given relative build path."""
    if os.path.basename(relpath).startswith('BUILD'):
      return relpath
    else:
      return os.path.join(relpath, 'BUILD')

  @classmethod
  def create_dir(cls, relpath):
    """Creates a directory under the buildroot.

    relpath: The relative path to the directory from the build root.
    """
    safe_mkdir(os.path.join(cls.build_root, relpath))

  @classmethod
  def create_file(cls, relpath, contents='', mode='w'):
    """Writes to a file under the buildroot.

    relpath:  The relative path to the file from the build root.
    contents: A string containing the contents of the file - '' by default..
    mode:     The mode to write to the file in - over-write by default.
    """
    with safe_open(os.path.join(cls.build_root, relpath), mode=mode) as fp:
      fp.write(contents)

  @classmethod
  def create_target(cls, relpath, target):
    """Adds the given target specification to the BUILD file at relpath.

    relpath: The relative path to the BUILD file from the build root.
    target:  A string containing the target definition as it would appear in a BUILD file.
    """
    cls.create_file(cls.build_path(relpath), target, mode='a')

  @classmethod
  def setUpClass(cls):
    cls.build_root = mkdtemp(suffix='_BUILD_ROOT')
    BuildRoot().path = cls.build_root
    cls.create_file('pants.ini')
    Target._clear_all_addresses()

  @classmethod
  def tearDownClass(cls):
    BuildRoot().reset()
    SourceRoot.reset()
    safe_rmtree(cls.build_root)

  @classmethod
  def target(cls, address):
    """Resolves the given target address to a Target object.

    address: The BUILD target address to resolve.

    Returns the corresponding Target or else None if the address does not point to a defined Target.
    """
    return Target.get(Address.parse(cls.build_root, address, is_relative=False))
