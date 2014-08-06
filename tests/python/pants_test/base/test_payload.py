# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import pytest

from pants.backend.core.wrapped_globs import Globs
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.base.build_file_aliases import BuildFileAliases
from pants.base.exceptions import TargetDefinitionException
from pants_test.base_test import BaseTest


class PayloadTest(BaseTest):
  @property
  def alias_groups(self):
    return BuildFileAliases.create(
      targets={
        'java_library': JavaLibrary,
      },
      context_aware_object_factories={
        'globs': Globs,
      },
    )

  def setUp(self):
    super(PayloadTest, self).setUp()

  def test_no_nested_globs(self):
    # nesting no longer allowed
    self.add_to_build_file('z/BUILD', 'java_library(name="z", sources=[globs("*")])')
    with pytest.raises(TargetDefinitionException):
      self.build_file_parser.scan(self.build_root)

  def test_flat_globs_list(self):
    # flattened allowed
    self.add_to_build_file('y/BUILD', 'java_library(name="y", sources=globs("*"))')
    self.build_file_parser.scan(self.build_root)

  def test_single_source(self):
    self.add_to_build_file('y/BUILD', 'java_library(name="y", sources=["Source.scala"])')
    self.build_file_parser.scan(self.build_root)
