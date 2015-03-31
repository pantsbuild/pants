# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from textwrap import dedent

from pants.backend.jvm.register import build_file_aliases as register_jvm
from pants.base.address import BuildFileAddress, SyntheticAddress
from pants.base.exceptions import TargetDefinitionException
from pants_test.base_test import BaseTest


class JvmBinaryTest(BaseTest):
  @property
  def alias_groups(self):
    return register_jvm()

  def test_simple(self):
    build_file = self.add_to_build_file('BUILD', dedent('''
    jvm_binary(name='foo',
      main='com.example.Foo',
      basename='foo-base',
    )
    '''))

    self.build_graph.inject_address_closure(BuildFileAddress(build_file, 'foo'))
    target = self.build_graph.get_target(SyntheticAddress.parse('//:foo'))
    self.assertEquals('com.example.Foo', target.main)
    self.assertEquals('foo-base', target.basename)

  def test_default_base(self):
    build_file = self.add_to_build_file('BUILD', dedent('''
    jvm_binary(name='foo',
      main='com.example.Foo',
    )
    '''))
    self.build_graph.inject_address_closure(BuildFileAddress(build_file, 'foo'))
    target = self.build_graph.get_target(SyntheticAddress.parse('//:foo'))
    self.assertEquals('foo', target.basename)

  def test_bad_source_declaration(self):
    build_file = self.add_to_build_file('BUILD', dedent('''
        jvm_binary(name='foo',
          main='com.example.Foo',
          source=['foo.py'],
        )
        '''))
    with self.assertRaisesRegexp(TargetDefinitionException,
                                 r'source must be a single'):
      self.build_graph.inject_address_closure(BuildFileAddress(build_file, 'foo'))

  def test_bad_main_declaration(self):
    build_file = self.add_to_build_file('BUILD', dedent('''
        jvm_binary(name='bar',
          main=['com.example.Bar'],
        )
        '''))
    with self.assertRaisesRegexp(TargetDefinitionException,
                                 r'main must be a fully'):
      self.build_graph.inject_address_closure(BuildFileAddress(build_file, 'bar'))
