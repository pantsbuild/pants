# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import xml.etree.ElementTree as ET

from pants_test.backend.jvm.tasks.jvm_compile.base_compile_integration_test import BaseCompileIT
from pants_test.backend.jvm.tasks.jvm_compile.utils import provide_compile_strategies


class ScalaCompileIntegrationTest(BaseCompileIT):
  @provide_compile_strategies
  def test_scala_compile(self, strategy):
    with self.do_test_compile('testprojects/src/scala/org/pantsbuild/testproject/unicode/shapeless',
                              strategy,
                              expected_files=['ShapelessExample.class']) as found:

      self.assertTrue(
          self.get_only(found, 'ShapelessExample.class').endswith(
              'org/pantsbuild/testproject/unicode/shapeless/ShapelessExample.class'))

  @provide_compile_strategies
  def test_scala_with_java_sources_compile(self, strategy):
    with self.do_test_compile('testprojects/src/scala/org/pantsbuild/testproject/javasources',
                              strategy,
                              expected_files=['ScalaWithJavaSources.class',
                                              'JavaSource.class']) as found:

      self.assertTrue(
          self.get_only(found, 'ScalaWithJavaSources.class').endswith(
              'org/pantsbuild/testproject/javasources/ScalaWithJavaSources.class'))

      self.assertTrue(
          self.get_only(found, 'JavaSource.class').endswith(
              'org/pantsbuild/testproject/javasources/JavaSource.class'))

  @provide_compile_strategies
  def test_scalac_plugin_compile(self, strategy):
    with self.do_test_compile('testprojects/src/scala/org/pantsbuild/testproject/scalac/plugin',
                              strategy,
                              expected_files=['HelloScalac.class', 'scalac-plugin.xml']) as found:

      self.assertTrue(
          self.get_only(found, 'HelloScalac.class').endswith(
              'org/pantsbuild/testproject/scalac/plugin/HelloScalac.class'))

      tree = ET.parse(self.get_only(found, 'scalac-plugin.xml'))
      root = tree.getroot()
      self.assertEqual('plugin', root.tag)
      self.assertEqual('hello_scalac', root.find('name').text)
      self.assertEqual('org.pantsbuild.testproject.scalac.plugin.HelloScalac',
                       root.find('classname').text)
