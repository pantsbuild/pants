# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from textwrap import dedent

from twitter.common.collections import OrderedSet

from pants_test.base_build_root_test import BaseBuildRootTest


class ScalaLibraryTest(BaseBuildRootTest):

  @classmethod
  def setUpClass(cls):
    super(ScalaLibraryTest, cls).setUpClass()

    cls.create_target('3rdparty', dedent('''
        jar_library(
          name='hub-and-spoke',
          dependencies=[
            jar('org.jalopy', 'hub-and-spoke', '0.0.1')
          ]
        )
        '''))

    cls.create_target('scala', dedent('''
        scala_library(
          name='lib',
          sources=[],
          java_sources=[
            pants('java:explicit_scala_dep'),
            pants('java:no_scala_dep'),
          ]
        )
        '''))

    cls.create_target('java', dedent('''
        java_library(
          name='explicit_scala_dep',
          sources=[],
          dependencies=[
            pants('scala:lib'),
            pants('3rdparty:hub-and-spoke'),
          ]
        )

        java_library(
          name='no_scala_dep',
          sources=[],
          dependencies=[]
        )
        '''))

    cls.lib_hub_and_spoke = cls.target('3rdparty:hub-and-spoke')
    cls.scala_library = cls.target('scala:lib')
    cls.java_library_explicit_dep = cls.target('java:explicit_scala_dep')
    cls.java_library_no_dep = cls.target('java:no_scala_dep')

  def test_mixed_linkage(self):
    self.assertEqual(OrderedSet(self.lib_hub_and_spoke.resolve()), self.scala_library.dependencies,
                     'The scala end of a mixed language logical lib should be linked with the java'
                     'code deps excluding itself.')

    deps = set(self.lib_hub_and_spoke.resolve())
    deps.add(self.scala_library)
    self.assertEqual(deps, set(self.java_library_explicit_dep.dependencies),
                     'The java end of a mixed language logical lib with an explicit dep should be '
                     'unaffected by linking.')

    self.assertEqual(OrderedSet([self.scala_library]), self.java_library_no_dep.dependencies,
                     'The java end of a mixed language logical lib with an no explicit dep should '
                     'be linked to scala.')

