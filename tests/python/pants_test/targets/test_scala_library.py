# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from textwrap import dedent

from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.targets.scala_jar_dependency import ScalaJarDependency
from pants.backend.jvm.targets.scala_library import ScalaLibrary
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.java.jar.jar_dependency import JarDependency
from pants_test.base_test import BaseTest


class ScalaLibraryTest(BaseTest):
  @property
  def alias_groups(self):
    return BuildFileAliases(
      targets={
        'scala_library': ScalaLibrary,
        'java_library': JavaLibrary,
        'jar_library': JarLibrary,
      },
      objects={
        'jar': JarDependency,
        'scala_jar': ScalaJarDependency,
      }
    )

  def setUp(self):
    super(ScalaLibraryTest, self).setUp()
    self.context(options={
      'scala-platform': {
        'version': '2.10'
      }
    })

    self.add_to_build_file('3rdparty', dedent("""
        jar_library(
          name='hub-and-spoke',
          jars=[
            jar('org.jalopy', 'hub-and-spoke', '0.0.1')
          ]
        )
        """))

    self.add_to_build_file('scala', dedent("""
        scala_library(
          name='lib',
          sources=[],
          java_sources=[
            'java:explicit_scala_dep',
            'java:no_scala_dep',
          ]
        )
        """))

    self.add_to_build_file('java', dedent("""
        java_library(
          name='explicit_scala_dep',
          sources=[],
          dependencies=[
            'scala:lib',
            '3rdparty:hub-and-spoke',
          ]
        )

        java_library(
          name='no_scala_dep',
          sources=[],
          dependencies=[]
        )
        """))

    self.lib_hub_and_spoke = self.target('3rdparty:hub-and-spoke')
    self.scala_library = self.target('scala:lib')
    self.java_library_explicit_dep = self.target('java:explicit_scala_dep')
    self.java_library_no_dep = self.target('java:no_scala_dep')

  def test_mixed_linkage(self):
    # Expect the scala_lib to include the jar_library lib_hub_and_spoke's jar as
    # well as one other jar.

    self.assertEqual(len(self.lib_hub_and_spoke.jar_dependencies), 1)
    self.assertEqual(len(self.scala_library.jar_dependencies), 2)
    self.assertTrue(
      self.lib_hub_and_spoke.jar_dependencies[0] in self.scala_library.jar_dependencies,
      'Expect the scala_lib to include the jar_library lib_hub_and_spoke\'s jar as well '
      'as one other jar.')

    self.assertEqual(set(self.scala_library.jar_dependencies),
                     set(self.java_library_explicit_dep.jar_dependencies),
                     'The java end of a mixed language logical lib with an explicit dep should be '
                     'unaffected by linking.')
