# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
from contextlib import contextmanager
from textwrap import dedent

from pants.backend.jvm.subsystems.scala_platform import ScalaPlatform
from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.targets.scala_library import ScalaLibrary
from pants.backend.jvm.tasks.scalastyle import FileExcluder, Scalastyle
from pants.base.exceptions import TaskError
from pants_test.jvm.nailgun_task_test_base import NailgunTaskTestBase
from pants_test.subsystem.subsystem_util import subsystem_instance
from pants_test.tasks.task_test_base import ensure_cached


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
    self.set_options(skip=False, config=scalastyle_config, excludes=excludes)
    return self.context(target_roots=target_roots)

  def _create_scalastyle_task(self, scalastyle_config):
    return self.prepare_execute(self._create_context(scalastyle_config))

  def setUp(self):
    super(ScalastyleTest, self).setUp()
    self.context()  # We don't need the context, but this ensures subsystem option registration.

  def test_initialize_config_no_config_settings(self):
    with self.scala_platform_setup():
      with self.assertRaises(Scalastyle.UnspecifiedConfig):
        self._create_scalastyle_task(scalastyle_config=None).validate_scalastyle_config()

  def test_initialize_config_config_setting_exist_but_invalid(self):
    with self.scala_platform_setup():
      with self.assertRaises(Scalastyle.MissingConfig):
        self._create_scalastyle_task(
          scalastyle_config='file_does_not_exist.xml').validate_scalastyle_config()

  def test_excludes_setting_exists_but_invalid(self):
    with self.scala_platform_setup():
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

  @contextmanager
  def scala_platform_setup(self):
    with subsystem_instance(ScalaPlatform):
      self.set_options_for_scope(ScalaPlatform.options_scope, version='2.10')

      yield

  @contextmanager
  def custom_scala_platform_setup(self):
    with subsystem_instance(ScalaPlatform):
      # We don't need to specify :scalac or :scala-repl since they are never being fetched.
      self.make_target('//:scalastyle',
                       JarLibrary,
                       jars=[JarDependency('org.scalastyle', 'scalastyle_2.10', '0.3.2')],
      )
      self.set_options_for_scope(ScalaPlatform.options_scope, version='custom')

      yield

  def test_get_non_synthetic_scala_targets(self):
    with self.scala_platform_setup():
      # scala_library - should remain.
      scala_target = self.make_target('a/scala:s', ScalaLibrary, sources=['Source.scala'])

      # scala_library but with java sources - should be filtered
      scala_target_with_java_source = self.make_target('a/scala_java:sj',
                                                       ScalaLibrary,
                                                       sources=['Source.java'])

      # java_library - should be filtered
      java_target = self.make_target('a/java:j', JavaLibrary, sources=['Source.java'])

      # synthetic scala_library - should be filtered
      synthetic_scala_target = self.make_target('a/synthetic_scala:ss',
                                                ScalaLibrary,
                                                sources=['SourceGenerated.scala'],
                                                derived_from=scala_target)

      result_targets = Scalastyle.get_non_synthetic_scala_targets([java_target,
                                                                   scala_target,
                                                                   scala_target_with_java_source,
                                                                   synthetic_scala_target])

      # Only the scala target should remain
      self.assertEquals(1, len(result_targets))
      self.assertEqual(scala_target, result_targets[0])

  def test_get_non_excluded_scala_sources(self):
    with self.scala_platform_setup():
      # this scala target has mixed *.scala and *.java sources.
      # the *.java source should be filtered out.
      scala_target_1 = self.make_target('a/scala_1:s1',
                                        ScalaLibrary,
                                        sources=['Source1.java', 'Source1.scala'])

      # this scala target has single *.scala source but will be excluded out
      # by the [scalastyle].[excludes] setting.
      scala_target_2 = self.make_target('a/scala_2:s2', ScalaLibrary, sources=['Source2.scala'])

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

      # Remember, we have the extra 'scala-library' dep target.
      self.assertEqual(3, len(context.targets()))

      # Now create the task and run the scala source and exclusion filtering.
      task = self.prepare_execute(context)

      result_sources = task.get_non_excluded_scala_sources(
        task.create_file_excluder(),
        task.get_non_synthetic_scala_targets(context.targets()))

      # Only the scala source from target 1 should remain
      self.assertEquals(1, len(result_sources))
      self.assertEqual('a/scala_1/Source1.scala', result_sources[0])

  @ensure_cached(Scalastyle, expected_num_artifacts=1)
  def test_end_to_end_pass(self):
    # Default scalastyle config (import grouping rule) and no excludes.
    with self.scala_platform_setup():
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
      scala_target = self.make_target('a/scala:pass', ScalaLibrary, sources=['pass.scala'])

      context = self._create_context(scalastyle_config=self._create_scalastyle_config_file(),
                                     target_roots=[scala_target])

      self.execute(context)

  def test_custom_end_to_end_pass(self):
    # Default scalastyle config (import grouping rule) and no excludes.
    with self.custom_scala_platform_setup():
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
      scala_target = self.make_target('a/scala:pass', ScalaLibrary, sources=['pass.scala'])

      context = self._create_context(scalastyle_config=self._create_scalastyle_config_file(),
                                     target_roots=[scala_target])

      self.execute(context)

  def test_fail(self):
    # Default scalastyle config (import grouping rule) and no excludes.
    with self.scala_platform_setup():
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
      scala_target = self.make_target('a/scala:fail', ScalaLibrary, sources=['fail.scala'])

      context = self._create_context(target_roots=[scala_target])

      with self.assertRaises(TaskError):
        self.execute(context)
