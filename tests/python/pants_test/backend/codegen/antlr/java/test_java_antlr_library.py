# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from textwrap import dedent

from pants.backend.codegen.antlr.java.java_antlr_library import JavaAntlrLibrary
from pants.base.exceptions import TargetDefinitionException
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants_test.test_base import TestBase


class JavaAntlrLibraryTest(TestBase):

  @classmethod
  def alias_groups(cls):
    return BuildFileAliases(targets={'java_antlr_library': JavaAntlrLibrary})

  def test_empty(self):
    with self.assertRaisesRegexp(TargetDefinitionException, "Missing required 'sources' parameter"):
      self.add_to_build_file('BUILD', dedent('''
        java_antlr_library(name='foo',
          sources=[],
        )'''))
      self.foo = self.target('//:foo')

  def test_valid(self):
    self.add_to_build_file('BUILD', dedent('''
      java_antlr_library(name='foo',
        sources=['foo'],
      )'''))
    self.foo = self.target('//:foo')
    self.assertIsInstance(self.foo, JavaAntlrLibrary)

  def test_invalid_compiler(self):
    with self.assertRaisesRegexp(TargetDefinitionException, "Illegal value for 'compiler'"):
      self.add_to_build_file('BUILD', dedent('''
        java_antlr_library(name='foo',
          sources=['foo'],
          compiler='antlr9'
        )'''))
      self.foo = self.target('//:foo')
