# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
from builtins import open
from textwrap import dedent

from pants.backend.jvm.subsystems.scala_platform import ScalaPlatform
from pants.backend.jvm.targets.junit_tests import JUnitTests
from pants.backend.jvm.targets.scala_library import ScalaLibrary
from pants.backend.jvm.tasks.scalafmt import ScalaFmtCheckFormat, ScalaFmtFormat
from pants.base.exceptions import TaskError
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.build_graph.resources import Resources
from pants.source.source_root import SourceRootConfig
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import fast_relpath
from pants_test.jvm.nailgun_task_test_base import NailgunTaskTestBase
from pants_test.subsystem.subsystem_util import init_subsystem


class ScalaFmtTestBase(NailgunTaskTestBase):
  @classmethod
  def alias_groups(cls):
    return super(ScalaFmtTestBase, cls).alias_groups().merge(
      BuildFileAliases(targets={'java_tests': JUnitTests,
                                'junit_tests': JUnitTests,
                                'scala_library': ScalaLibrary}))

  def setUp(self):
    super(ScalaFmtTestBase, self).setUp()

    init_subsystem(ScalaPlatform)
    init_subsystem(SourceRootConfig)

    self.configuration = self.create_file(
      relpath='build-support/scalafmt/config',
      contents=dedent("""
      align.arrowEnumeratorGenerator = true
      align.openParenCallSite = false
      align.openParenDefnSite = false
      assumeStandardLibraryStripMargin = false
      binPack.parentConstructors = false
      continuationIndent.callSite = 4
      continuationIndent.defnSite = 4
      maxColumn = 100
      newlines.sometimesBeforeColonInMethodReturnType = true
      spaces.afterTripleEquals = true
      spaces.inImportCurlyBraces = false
      """)
    )

    self.test_file_contents = dedent(
      """
      package org.pantsbuild.badscalastyle

      /**
       * These comments are formatted incorrectly
       * and the parameter list is too long for one line
       */
      case class ScalaStyle(one: String,two: String,three: String,four: String,
          five: String,six: String,seven: String,eight: String,  nine: String)

      class Person(name: String,age: Int,astrologicalSign: String,
          shoeSize: Int,
          favoriteColor: java.awt.Color) {
        def getAge:Int={return age}
        def sum(longvariablename: List[String]): Int = {
          longvariablename.map(_.toInt).foldLeft(0)(_ + _)
        }
      }
      """
    )
    self.test_file = self.create_file(
      relpath='src/scala/org/pantsbuild/badscalastyle/BadScalaStyle.scala',
      contents=self.test_file_contents,
    )
    self.library = self.make_target(spec='src/scala/org/pantsbuild/badscalastyle',
                                    sources=['BadScalaStyle.scala'],
                                    target_type=ScalaLibrary)
    self.as_resources = self.make_target(spec='src/scala/org/pantsbuild/badscalastyle:as_resources',
                                         target_type=Resources,
                                         sources=['BadScalaStyle.scala'],
                                         description='Depends on the same sources as the target '
                                                     'above, but as resources.')


class ScalaFmtCheckFormatTest(ScalaFmtTestBase):

  @classmethod
  def task_type(cls):
    return ScalaFmtCheckFormat

  def test_scalafmt_fail_default_config(self):
    self.set_options(skip=False)
    context = self.context(target_roots=self.library)
    with self.assertRaises(TaskError):
      self.execute(context)

  def test_scalafmt_fail(self):
    self.set_options(skip=False, configuration=self.configuration)
    context = self.context(target_roots=self.library)
    with self.assertRaises(TaskError):
      self.execute(context)

  def test_scalafmt_disabled(self):
    self.set_options(skip=True)
    self.execute(self.context(target_roots=self.library))

  def test_scalafmt_ignore_resources(self):
    self.set_options(skip=False, configuration=self.configuration)
    context = self.context(target_roots=self.as_resources)
    self.execute(context)


class ScalaFmtFormatTest(ScalaFmtTestBase):

  @classmethod
  def task_type(cls):
    return ScalaFmtFormat

  def test_scalafmt_format_default_config(self):
    self.format_file_and_verify_fmt(skip=False)

  def test_scalafmt_format(self):
    self.format_file_and_verify_fmt(skip=False, configuration=self.configuration)

  def format_file_and_verify_fmt(self, **options):
    self.set_options(**options)

    lint_options_scope = 'sfcf'
    check_fmt_task_type = self.synthesize_task_subtype(ScalaFmtCheckFormat, lint_options_scope)
    self.set_options_for_scope(lint_options_scope, **options)

    # format an incorrectly formatted file.
    context = self.context(for_task_types=[check_fmt_task_type], target_roots=self.library)
    self.execute(context)

    with open(self.test_file, 'r') as fp:
      self.assertNotEqual(self.test_file_contents, fp.read())

    # verify that the lint check passes.
    check_fmt_workdir = os.path.join(self.pants_workdir, check_fmt_task_type.stable_name())
    check_fmt_task = check_fmt_task_type(context, check_fmt_workdir)
    check_fmt_task.execute()

  def test_output_dir(self):
    with temporary_dir() as output_dir:
      self.set_options(skip=False, output_dir=output_dir)

      lint_options_scope = 'sfcf'
      check_fmt_task_type = self.synthesize_task_subtype(ScalaFmtCheckFormat, lint_options_scope)
      self.set_options_for_scope(lint_options_scope)

      # format an incorrectly formatted file.
      context = self.context(
        for_task_types=[check_fmt_task_type],
        target_roots=self.library,
      )
      self.execute(context)

      with open(self.test_file, 'r') as fp:
        self.assertEqual(self.test_file_contents, fp.read())

      relative_test_file = fast_relpath(self.test_file, self.build_root)
      with open(os.path.join(output_dir, relative_test_file), 'r') as fp:
        self.assertNotEqual(self.test_file_contents, fp.read())
