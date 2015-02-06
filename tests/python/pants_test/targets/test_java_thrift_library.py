# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from textwrap import dedent

import pytest

from pants.backend.codegen.targets.java_thrift_library import JavaThriftLibrary
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.base.build_file_aliases import BuildFileAliases
from pants_test.base.context_utils import create_config
from pants_test.base_test import BaseTest


class JavaThriftLibraryDefaultsTest(BaseTest):
  @property
  def alias_groups(self):
    return BuildFileAliases.create(
      targets={
        'java_thrift_library': JavaThriftLibrary,
        'java_library': JavaLibrary,
      }
    )

  def setUp(self):
    super(JavaThriftLibraryDefaultsTest, self).setUp()

    self.add_to_build_file('thrift', dedent('''
        java_thrift_library(
          name='default',
          sources=[],
        )

        java_thrift_library(
          name='language',
          sources=[],
          language='scala',
        )

        java_thrift_library(
          name='rpc_style',
          sources=[],
          rpc_style='ostrich',
        )

        java_library(
          name='invalid',
          sources=[]
        )
        '''))

    self.target_default = self.target('thrift:default')
    self.target_language = self.target('thrift:language')
    self.target_rpc_style = self.target('thrift:rpc_style')
    self.target_invalid = self.target('thrift:invalid')

  @staticmethod
  def create_defaults(ini=''):
    config = create_config(ini)
    return JavaThriftLibrary.Defaults(config)

  def test_invalid(self):
    defaults = self.create_defaults()
    with pytest.raises(ValueError):
      defaults.get_compiler(self.target_invalid)

  def test_hardwired_defaults(self):
    defaults = self.create_defaults()
    self.assertEqual('thrift', defaults.get_compiler(self.target_default))
    self.assertEqual('java', defaults.get_language(self.target_default))
    self.assertEqual('sync', defaults.get_rpc_style(self.target_default))

  def test_configured_defaults(self):
    defaults = self.create_defaults(dedent('''
        [java-thrift-library]
        compiler: scrooge
        language: scala
        rpc_style: finagle
        '''))

    self.assertEqual('scrooge', defaults.get_compiler(self.target_default))
    self.assertEqual('scala', defaults.get_language(self.target_default))
    self.assertEqual('finagle', defaults.get_rpc_style(self.target_default))

  def test_explicit_values(self):
    defaults = self.create_defaults()
    self.assertEqual('scala', defaults.get_language(self.target_language))
    self.assertEqual('ostrich', defaults.get_rpc_style(self.target_rpc_style))
