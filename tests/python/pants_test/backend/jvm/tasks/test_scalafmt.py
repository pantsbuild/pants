# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from textwrap import dedent
from uuid import uuid4

from pants.backend.jvm.subsystems.scala_platform import ScalaPlatform
from pants.backend.jvm.subsystems.scoverage_platform import ScoveragePlatform
from pants.backend.jvm.targets.junit_tests import JUnitTests
from pants.backend.jvm.targets.scala_library import ScalaLibrary
from pants.backend.jvm.tasks.scalafmt import ScalaFmtCheckFormat, ScalaFmtFormat, ScalaFmtSubsystem
from pants.base.exceptions import TaskError
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.build_graph.resources import Resources
from pants.source.source_root import SourceRootConfig
from pants.testutil.jvm.nailgun_task_test_base import NailgunTaskTestBase
from pants.testutil.subsystem.util import init_subsystem
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import fast_relpath


class ScalaFmtTestBase(NailgunTaskTestBase):
  @classmethod
  def alias_groups(cls):
    return super().alias_groups().merge(
      BuildFileAliases(targets={'junit_tests': JUnitTests,
                                'scala_library': ScalaLibrary}))

  def setUp(self):
    super().setUp()

    init_subsystem(ScalaPlatform)
    init_subsystem(ScoveragePlatform)
    init_subsystem(SourceRootConfig)
    init_subsystem(ScalaFmtSubsystem)

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

  def _execute_native_image(self, num_sources=1, **kwargs):
    self.set_options(skip=False, **kwargs)
    self.set_options_for_scope('scalafmt', use_native_image=True)

    uuid = '_' + str(uuid4()).replace('-', '_')

    more_sources = [
      self.create_file(relpath=f'src/scala/org/pantsbuild/badscalastyle/BadScalaStyle{i}.scala',
                       contents=self.test_file_contents)
      for i in range(0, num_sources)
    ]
    generated_library = self.make_target(spec=f'src/scala/org/pantsbuild/badscalastyle:{uuid}',
                                         sources=[f'BadScalaStyle{i}.scala'
                                                  for i in range(0, num_sources)],
                                         target_type=ScalaLibrary)

    context = self.context(target_roots=generated_library)
    task = self.execute(context)

    # Assert that it ran successfully.
    for src in more_sources:
      with open(src, 'r') as fp:
        self.assertNotEqual(self.test_file_contents, fp.read())

    # Assert that the native-image executable was most recently used.
    scalafmt_native_image_basedir = ScalaFmtSubsystem.global_instance().select()

    all_source_paths = []
    for prefix_args, source_paths in task._all_command_lines:
      executable_file = prefix_args[0]
      self.assertTrue(executable_file.startswith(scalafmt_native_image_basedir))
      all_source_paths.append(source_paths)

    return all_source_paths

  def _assert_num_files_per_process_matches(self, all_source_paths, all_num_files):
    self.assertEqual(len(all_source_paths), len(all_num_files))
    for paths, expected_num_files in zip(all_source_paths, all_num_files):
      self.assertEqual(len(paths), expected_num_files)

  def test_native_image_execution(self):
    self._execute_native_image()

  def test_native_image_threading_worker_count(self):
    all_source_paths = self._execute_native_image(num_sources=4, worker_count=2)
    self._assert_num_files_per_process_matches(all_source_paths,
                                               all_num_files=[2, 2])

  def test_native_image_threading_uneven_divisor(self):
    all_source_paths = self._execute_native_image(num_sources=5, worker_count=3)
    self._assert_num_files_per_process_matches(all_source_paths,
                                               all_num_files=[2, 2, 1])

  def test_native_image_threading_massive_process_limit(self):
    all_source_paths = self._execute_native_image(num_sources=2, worker_count=3)
    self._assert_num_files_per_process_matches(all_source_paths,
                                               all_num_files=[1, 1])

  def test_native_image_threading_files_per_worker(self):
    all_source_paths = self._execute_native_image(num_sources=2, files_per_worker=1)
    self._assert_num_files_per_process_matches(all_source_paths,
                                               all_num_files=[1, 1])

  def test_native_image_threading_uneven_files_per_worker(self):
    all_source_paths = self._execute_native_image(num_sources=5, files_per_worker=3)
    self._assert_num_files_per_process_matches(all_source_paths,
                                               all_num_files=[3, 2])

  def test_native_image_threading_massive_files_per_process(self):
    all_source_paths = self._execute_native_image(num_sources=2, files_per_worker=5)
    self._assert_num_files_per_process_matches(all_source_paths,
                                               all_num_files=[2])
