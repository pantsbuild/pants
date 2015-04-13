# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
from textwrap import dedent

from pants.backend.jvm.targets.scala_library import ScalaLibrary
from pants.backend.jvm.tasks.scalastyle import FileExcluder, Scalastyle
from pants.base.address import BuildFileAddress
from pants.base.exceptions import TaskError
from pants_test.jvm.nailgun_task_test_base import NailgunTaskTestBase


logger = logging.getLogger(__name__)


class ScalastyleTest(NailgunTaskTestBase):
  """Tests for the class Scalastyle."""

  @classmethod
  def task_type(cls):
    return Scalastyle

  #
  # Internal test helper section
  #

  def _create_scalastyle_config_file(self, rules=None):
    # put a default rule there if rules are not specified.
    rules = rules or ['org.scalastyle.scalariform.ImportGroupingChecker']
    rule_section_xml = ''
    for rule in rules:
      rule_section_xml += dedent("""
        <check level="error" class="{rule}" enabled="true"></check>
      """.format(rule=rule))
    return self.create_file(
      relpath='scalastyle_config.xml',
      contents=dedent("""
        <scalastyle commentFilter="enabled">
          <name>Test Scalastyle configuration</name>
          {rule_section_xml}
        </scalastyle>
      """.format(rule_section_xml=rule_section_xml)))

  def _create_scalastyle_excludes_file(self, exclude_patterns=None):
    return self.create_file(
      relpath='scalastyle_excludes.txt',
      contents='\n'.join(exclude_patterns) if exclude_patterns else '')

  def _create_context(self, scalastyle_config=None, excludes=None, target_roots=None):
    # If config is not specified, then we override pants.ini scalastyle such that
    # we have a default scalastyle config xml but with empty excludes.
    options = {
      'skip': False,
    }
    if scalastyle_config:
      options['config'] = scalastyle_config
    if excludes:
      options['excludes'] = excludes

    return self.context(
      options={
        self.options_scope: options
      },
      target_roots=target_roots)

  def _create_scalastyle_task(self, scalastyle_config):
    return self.create_task(self._create_context(scalastyle_config), self.build_root)

  def _create_scalastyle_task_from_context(self, context):
    return self.create_task(context, self.build_root)

  def test_initialize_config_no_config_settings(self):
    with self.assertRaises(Scalastyle.UnspecifiedConfig):
      self._create_scalastyle_task(scalastyle_config=None).validate_scalastyle_config()

  def test_initialize_config_config_setting_exist_but_invalid(self):
    with self.assertRaises(Scalastyle.MissingConfig):
      self._create_scalastyle_task(
        scalastyle_config='file_does_not_exist.xml').validate_scalastyle_config()

  def test_excludes_setting_exists_but_invalid(self):
    with self.assertRaises(TaskError):
      FileExcluder('file_does_not_exist.txt', logger)

  def test_excludes_parsed_loaded_correctly(self):
    excludes_text = dedent('''
      # ignore C++
      .*\.cpp

      # ignore python
      .*\.py''')
    excluder = FileExcluder(self._create_scalastyle_excludes_file([excludes_text]), logger)
    self.assertEqual(2, len(excluder.excludes))
    self.assertTrue(excluder.should_include('com/some/org/x.scala'))
    self.assertFalse(excluder.should_include('com/some/org/y.cpp'))
    self.assertFalse(excluder.should_include('z.py'))

  def test_get_non_synthetic_scala_targets(self):
    # scala_library - should remain.
    scala_target_address = BuildFileAddress(
      self.add_to_build_file(
        'a/scala/BUILD', 'scala_library(name="s", sources=["Source.scala"])'),
      's')
    self.build_graph.inject_address_closure(scala_target_address)
    scala_target = self.build_graph.get_target(scala_target_address)

    # scala_library but with java sources - should be filtered
    scala_target_java_source_address = BuildFileAddress(
      self.add_to_build_file(
        'a/scala_java/BUILD', 'scala_library(name="sj", sources=["Source.java"])'),
      'sj')
    self.build_graph.inject_address_closure(scala_target_java_source_address)
    scala_target_with_java_source = self.build_graph.get_target(
      scala_target_java_source_address)

    # java_library - should be filtered
    java_target_address = BuildFileAddress(
      self.add_to_build_file(
        'a/java/BUILD', 'java_library(name="j", sources=["Source.java"])'),
      'j')
    self.build_graph.inject_address_closure(java_target_address)
    java_target = self.build_graph.get_target(java_target_address)

    # synthetic scala_library - should be filtered
    synthetic_scala_target = self.make_target('a/synthetic_scala:ss', ScalaLibrary)

    # Create a custom context so we can manually inject multiple targets of different source types
    # and synthetic vs non-synthetic to test the target filtering logic.
    context = self._create_context(
      target_roots=[
        java_target,
        scala_target,
        scala_target_with_java_source,
        synthetic_scala_target
      ])

    # scala_library would bring in 'scala-library defined in BUILD.tools
    # so we have an extra target here.
    self.assertEqual(5, len(context.targets()))

    # Now create the task and run the non_synthetic scala-only filtering.
    task = self._create_scalastyle_task_from_context(context)
    result_targets = task.get_non_synthetic_scala_targets(context.targets())

    # Only the scala target should remain
    self.assertEquals(1, len(result_targets))
    self.assertEqual(scala_target, result_targets[0])

  def test_get_non_excluded_scala_sources(self):
    # this scala target has mixed *.scala and *.java sources.
    # the *.java source should be filtered out.
    scala_target_address_1 = BuildFileAddress(
      self.add_to_build_file(
        'a/scala_1/BUILD',
        'scala_library(name="s1", sources=["Source1.java", "Source1.scala"])'),
      's1')
    self.build_graph.inject_address_closure(scala_target_address_1)
    scala_target_1 = self.build_graph.get_target(scala_target_address_1)

    # this scala target has single *.scala source but will be excluded out
    # by the [scalastyle].[excludes] setting.
    scala_target_address_2 = BuildFileAddress(
      self.add_to_build_file(
        'a/scala_2/BUILD', 'scala_library(name="s2", sources=["Source2.scala"])'),
      's2')
    self.build_graph.inject_address_closure(scala_target_address_2)
    scala_target_2 = self.build_graph.get_target(scala_target_address_2)

    # Create a custom context so we can manually inject scala targets
    # with mixed sources in them to test the source filtering logic.
    context = self._create_context(
      scalastyle_config=self._create_scalastyle_config_file(),
      excludes=self._create_scalastyle_excludes_file(['a/scala_2/Source2.scala']),
      target_roots=[
        scala_target_1,
        scala_target_2
      ]
    )

    # Remember, we have the extra 'scala-library-2.9.3' dep target.
    self.assertEqual(3, len(context.targets()))

    # Now create the task and run the scala source and exclusion filtering.
    task = self._create_scalastyle_task_from_context(context)

    result_sources = task.get_non_excluded_scala_sources(
      task.create_file_excluder(),
      task.get_non_synthetic_scala_targets(context.targets()))

    # Only the scala source from target 1 should remain
    self.assertEquals(1, len(result_sources))
    self.assertEqual('a/scala_1/Source1.scala', result_sources[0])

  def test_end_to_end_pass(self):
    # Default scalastyle config (import grouping rule) and no excludes.

    # Create a scala source that would PASS ImportGroupingChecker rule.
    self.create_file(
      relpath='a/scala/pass.scala',
      contents=dedent("""
        import java.util
        object HelloWorld {
           def main(args: Array[String]) {
              println("Hello, world!")
           }
        }
      """))
    scala_target_address = BuildFileAddress(
      self.add_to_build_file(
        'a/scala/BUILD', 'scala_library(name="pass", sources=["pass.scala"])'),
      'pass')
    self.build_graph.inject_address_closure(scala_target_address)
    scala_target = self.build_graph.get_target(scala_target_address)

    context = self._create_context(scalastyle_config=self._create_scalastyle_config_file(),
                                   target_roots=[scala_target])

    self.execute(context)

  def test_fail(self):
    # Default scalastyle config (import grouping rule) and no excludes.

    # Create a scala source that would FAIL ImportGroupingChecker rule.
    self.create_file(
      relpath='a/scala/fail.scala',
      contents=dedent("""
        import java.io._
        object HelloWorld {
           def main(args: Array[String]) {
              println("Hello, world!")
           }
        }
        import java.util._
      """))
    scala_target_address = BuildFileAddress(
      self.add_to_build_file(
        'a/scala/BUILD', 'scala_library(name="fail", sources=["fail.scala"])'),
      'fail')
    self.build_graph.inject_address_closure(scala_target_address)
    scala_target = self.build_graph.get_target(scala_target_address)

    context = self._create_context(target_roots=[scala_target])

    with self.assertRaises(TaskError):
      self.execute(context)
