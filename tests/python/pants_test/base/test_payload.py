# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import pytest

from pants.backend.core.wrapped_globs import Globs
from pants.backend.jvm.targets.scala_library import ScalaLibrary
from pants.base.build_file import BuildFile
from pants_test.base_test import BaseTest


class PayloadTest(BaseTest):
  @property
  def alias_groups(self):
    return {
      'target_aliases': {
        'scala_library': ScalaLibrary,
      },
      'applicative_path_relative_utils': {
        'globs': Globs,
      },
    }

  def setUp(self):
    super(PayloadTest, self).setUp()

  def test_no_nested_globs(self):
    # nesting no longer allowed
    self.add_to_build_file('z/BUILD', 'scala_library(name="z", sources=[globs("*")])')
    build_file_z = BuildFile(self.build_root, 'z/BUILD')
    with pytest.raises(ValueError):
      self.build_file_parser.scan(self.build_root)

  def test_flat_globs_list(self):
    # flattened allowed
    self.add_to_build_file('y/BUILD', 'scala_library(name="y", sources=globs("*"))')
    self.build_file_parser.scan(self.build_root)

  def test_single_source(self):
    self.add_to_build_file('y/BUILD', 'scala_library(name="y", sources="Source.scala")')
    self.build_file_parser.scan(self.build_root)
