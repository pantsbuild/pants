# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import pytest

from pants.backend.codegen.targets.java_thrift_library import JavaThriftLibrary
from pants.base.exceptions import TargetDefinitionException
from pants_test.base_test import BaseTest


class JavaThriftLibraryTest(BaseTest):

  def test_defaults(self):
    target = self.make_target(spec=':t1',
                              target_type=JavaThriftLibrary,
                              sources=[])
    self.assertEquals('sync', target.rpc_style)
    self.assertEquals('thrift', target.compiler)
    self.assertEquals('java', target.language)

  def test_mixed(self):
    target = self.make_target(spec=':t1',
                              target_type=JavaThriftLibrary,
                              rpc_style='finagle',
                              sources=[])
    self.assertEquals('finagle', target.rpc_style)
    self.assertEquals('thrift', target.compiler)
    self.assertEquals('java', target.language)

  def test_invalid_value(self):
    with pytest.raises(TargetDefinitionException):
      self.make_target(spec=':t1',
                       target_type=JavaThriftLibrary,
                       rpc_style='xyz',
                       sources=[])

    with pytest.raises(TargetDefinitionException):
      self.make_target(spec=':t1',
                       target_type=JavaThriftLibrary,
                       compiler='unknown',
                       sources=[])

    with pytest.raises(TargetDefinitionException):
      self.make_target(spec=':t1',
                       target_type=JavaThriftLibrary,
                       language='unknown',
                       sources=[])
