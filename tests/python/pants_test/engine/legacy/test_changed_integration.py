# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shutil
import subprocess
import unittest
from contextlib import contextmanager
from textwrap import dedent

from pants.base.build_environment import get_buildroot
from pants.util.contextutil import environment_as, temporary_dir
from pants.util.dirutil import safe_delete, safe_mkdir, safe_open, touch
from pants_test.base_test import TestGenerator
from pants_test.pants_run_integration_test import PantsRunIntegrationTest, ensure_engine
from pants_test.testutils.git_util import initialize_repo


def lines_to_set(str_or_list):
  if isinstance(str_or_list, list):
    return set(str_or_list)
  else:
    return set(x for x in str(str_or_list).split('\n') if x)


@contextmanager
def mutated_working_copy(files_to_mutate, to_append='\n '):
  """Given a list of files, append whitespace to each of them to trigger a git diff - then reset."""
  assert to_append, 'to_append may not be empty'

  for f in files_to_mutate:
    with open(f, 'ab') as fh:
      fh.write(to_append)
  try:
    yield
  finally:
    seek_point = len(to_append) * -1
    for f in files_to_mutate:
      with open(f, 'ab') as fh:
        fh.seek(seek_point, os.SEEK_END)
        fh.truncate()


@contextmanager
def create_isolated_git_repo():
  # Isolated Git Repo Structure:
  # worktree
  # |--README
  # |--pants.ini
  # |--3rdparty
  #    |--BUILD
  # |--src
  #    |--resources
  #       |--org/pantsbuild/resourceonly
  #          |--BUILD
  #          |--README.md
  #    |--java
  #       |--org/pantsbuild/helloworld
  #          |--BUILD
  #          |--helloworld.java
  #    |--python
  #       |--python_targets
  #          |--BUILD
  #          |--test_binary.py
  #          |--test_library.py
  #          |--test_unclaimed_src.py
  #       |--sources
  #          |--BUILD
  #          |--sources.py
  #          |--sources.txt
  # |--tests
  #    |--scala
  #       |--org/pantsbuild/cp-directories
  #          |--BUILD
  #          |--ClasspathDirectoriesSpec.scala
  with temporary_dir(root_dir=get_buildroot()) as worktree:
    def create_file(path, content):
      """Creates a file in the isolated git repo."""
      write_path = os.path.join(worktree, path)
      with safe_open(write_path, 'w') as f:
        f.write(dedent(content))
      return write_path

    def copy_into(path, to_path=None):
      """Copies a file from the real git repo into the isolated git repo."""
      write_path = os.path.join(worktree, to_path or path)
      if os.path.isfile(path):
        safe_mkdir(os.path.dirname(write_path))
        shutil.copyfile(path, write_path)
      else:
        shutil.copytree(path, write_path)
      return write_path

    create_file('README', 'N.B. This is just a test tree.')
    create_file('pants.ini',
      """
      [GLOBAL]
      pythonpath: [
          "{0}/contrib/go/src/python",
          "{0}/pants-plugins/src/python"
        ]
      backend_packages: +[
          "internal_backend.utilities",
          "pants.contrib.go"
        ]
      """.format(get_buildroot())
    )
    copy_into('.gitignore')

    with initialize_repo(worktree=worktree, gitdir=os.path.join(worktree, '.git')) as git:
      def add_to_git(commit_msg, *files):
        git.add(*files)
        git.commit(commit_msg)

      add_to_git('a go target with default sources',
        create_file('src/go/tester/BUILD', 'go_binary()'),
        create_file('src/go/tester/main.go',
          """
          package main
          import "fmt"
          func main() {
            fmt.Println("hello, world")
          }
          """
        )
      )

      add_to_git('resource file',
        create_file('src/resources/org/pantsbuild/resourceonly/BUILD',
          """
          resources(
            name='resource',
            sources=['README.md']
          )
          """
        ),
        create_file('src/resources/org/pantsbuild/resourceonly/README.md', 'Just a resource.')
      )

      add_to_git('hello world java program with a dependency on a resource file',
        create_file('src/java/org/pantsbuild/helloworld/BUILD',
          """
          jvm_binary(
            dependencies=[
              'src/resources/org/pantsbuild/resourceonly:resource',
            ],
            source='helloworld.java',
            main='org.pantsbuild.helloworld.HelloWorld',
          )
          """
        ),
        create_file('src/java/org/pantsbuild/helloworld/helloworld.java',
          """
          package org.pantsbuild.helloworld;

          class HelloWorld {
            public static void main(String[] args) {
              System.out.println("Hello, World!\n");
            }
          }
          """
        )
      )

      add_to_git('scala test target',
        copy_into(
          'testprojects/tests/scala/org/pantsbuild/testproject/cp-directories',
          'tests/scala/org/pantsbuild/cp-directories'
        )
      )

      add_to_git('python targets',
        copy_into('testprojects/src/python/python_targets', 'src/python/python_targets')
      )

      add_to_git('a python_library with resources=["filename"]',
        copy_into('testprojects/src/python/sources', 'src/python/sources')
      )

      add_to_git('3rdparty/BUILD', copy_into('3rdparty/BUILD'))

      with environment_as(PANTS_BUILDROOT_OVERRIDE=worktree):
        yield worktree


class ChangedIntegrationTest(PantsRunIntegrationTest, TestGenerator):

  TEST_MAPPING = {
    # A `jvm_binary` with `source='file.name'`.
    'src/java/org/pantsbuild/helloworld/helloworld.java': dict(
      none=['src/java/org/pantsbuild/helloworld:helloworld'],
      direct=['src/java/org/pantsbuild/helloworld:helloworld'],
      transitive=['src/java/org/pantsbuild/helloworld:helloworld']
    ),
    # A `python_binary` with `source='file.name'`.
    'src/python/python_targets/test_binary.py': dict(
      none=['src/python/python_targets:test'],
      direct=['src/python/python_targets:test'],
      transitive=['src/python/python_targets:test']
    ),
    # A `python_library` with `sources=['file.name']`.
    'src/python/python_targets/test_library.py': dict(
      none=['src/python/python_targets:test_library'],
      direct=['src/python/python_targets:test',
              'src/python/python_targets:test_library',
              'src/python/python_targets:test_library_direct_dependee'],
      transitive=['src/python/python_targets:test',
                  'src/python/python_targets:test_library',
                  'src/python/python_targets:test_library_direct_dependee',
                  'src/python/python_targets:test_library_transitive_dependee',
                  'src/python/python_targets:test_library_transitive_dependee_2',
                  'src/python/python_targets:test_library_transitive_dependee_3',
                  'src/python/python_targets:test_library_transitive_dependee_4']
    ),
    # A `resources` target with `sources=['file.name']` referenced by a `java_library` target.
    'src/resources/org/pantsbuild/resourceonly/README.md': dict(
      none=['src/resources/org/pantsbuild/resourceonly:resource'],
      direct=['src/java/org/pantsbuild/helloworld:helloworld',
              'src/resources/org/pantsbuild/resourceonly:resource'],
      transitive=['src/java/org/pantsbuild/helloworld:helloworld',
                  'src/resources/org/pantsbuild/resourceonly:resource'],
    ),
    # A `python_library` with `sources=['file.name'] .
    'src/python/sources/sources.py': dict(
      none=['src/python/sources:sources'],
      direct=['src/python/sources:sources'],
      transitive=['src/python/sources:sources']
    ),
    # A `scala_library` with `sources=['file.name']`.
    'tests/scala/org/pantsbuild/cp-directories/ClasspathDirectoriesSpec.scala': dict(
      none=['tests/scala/org/pantsbuild/cp-directories:cp-directories'],
      direct=['tests/scala/org/pantsbuild/cp-directories:cp-directories'],
      transitive=['tests/scala/org/pantsbuild/cp-directories:cp-directories']
    ),
    # A `go_binary` with default sources.
    'src/go/tester/main.go': dict(
      none=['src/go/tester:tester'],
      direct=['src/go/tester:tester'],
      transitive=['src/go/tester:tester']
    ),
    # An unclaimed source file.
    'src/python/python_targets/test_unclaimed_src.py': dict(
      none=[],
      direct=[],
      transitive=[]
    )
  }

  @classmethod
  def generate_tests(cls):
    """Generates tests on the class for better reporting granularity than an opaque for loop test."""
    def safe_filename(f):
      return f.replace('/', '_').replace('.', '_')

    for filename, dependee_mapping in cls.TEST_MAPPING.items():
      for dependee_type in dependee_mapping.keys():
        # N.B. The parameters here are used purely to close over the respective loop variables.
        def inner_integration_coverage_test(self, filename=filename, dependee_type=dependee_type):
          with create_isolated_git_repo() as worktree:
            # Mutate the working copy so we can do `--changed-parent=HEAD` deterministically.
            with mutated_working_copy([os.path.join(worktree, filename)]):
              stdout = self.assert_changed_new_equals_old(
                ['--changed-include-dependees={}'.format(dependee_type), '--changed-parent=HEAD'],
                test_list=True
              )

              self.assertEqual(
                lines_to_set(self.TEST_MAPPING[filename][dependee_type]),
                lines_to_set(stdout)
              )

        cls.add_test(
          'test_changed_coverage_{}_{}'.format(dependee_type, safe_filename(filename)),
          inner_integration_coverage_test
        )

  def assert_changed_new_equals_old(self, extra_args, success=True, test_list=False):
    args = ['-q', 'changed'] + extra_args
    changed_run = self.do_command(*args, success=success, enable_v2_engine=False)
    engine_changed_run = self.do_command(*args, success=success, enable_v2_engine=True)
    self.assertEqual(
      lines_to_set(changed_run.stdout_data), lines_to_set(engine_changed_run.stdout_data)
    )

    if test_list:
      # In the v2 engine, `--changed-*` options can alter the specs of any goal - test with `list`.
      list_args = ['-q', 'list'] + extra_args
      engine_list_run = self.do_command(*list_args, success=success, enable_v2_engine=True)
      self.assertEqual(
        lines_to_set(changed_run.stdout_data), lines_to_set(engine_list_run.stdout_data)
      )

    # If we get to here without asserting, we know all copies of stdout are identical - return one.
    return changed_run.stdout_data

  @ensure_engine
  def test_changed_options_scope_shadowing(self):
    """Tests that the `test-changed` scope overrides `changed` scope."""
    changed_src = 'src/python/python_targets/test_library.py'
    expected_target = self.TEST_MAPPING[changed_src]['none'][0]
    expected_set = {expected_target}
    not_expected_set = set(self.TEST_MAPPING[changed_src]['transitive']).difference(expected_set)

    with create_isolated_git_repo() as worktree:
      with mutated_working_copy([os.path.join(worktree, changed_src)]):
        pants_run = self.run_pants([
          '-ldebug',   # This ensures the changed target name shows up in the pants output.
          'test-changed',
          '--test-changed-changes-since=HEAD',
          '--test-changed-include-dependees=none',     # This option should be used.
          '--changed-include-dependees=transitive'     # This option should be stomped on.
        ])

      self.assert_success(pants_run)

      for expected_item in expected_set:
        self.assertIn(expected_item, pants_run.stdout_data)

      for not_expected_item in not_expected_set:
        if expected_target.startswith(not_expected_item):
          continue  # Ignore subset matches.
        self.assertNotIn(not_expected_item, pants_run.stdout_data)

  @ensure_engine
  def test_changed_options_scope_positional(self):
    changed_src = 'src/python/python_targets/test_library.py'
    expected_set = set(self.TEST_MAPPING[changed_src]['transitive'])

    with create_isolated_git_repo() as worktree:
      with mutated_working_copy([os.path.join(worktree, changed_src)]):
        pants_run = self.run_pants([
          '-ldebug',   # This ensures the changed target names show up in the pants output.
          'test-changed',
          '--changes-since=HEAD',
          '--include-dependees=transitive'
        ])

      self.assert_success(pants_run)
      for expected_item in expected_set:
        self.assertIn(expected_item, pants_run.stdout_data)

  @ensure_engine
  def test_test_changed_exclude_target(self):
    changed_src = 'src/python/python_targets/test_library.py'
    exclude_target_regexp = r'_[0-9]'
    excluded_set = {'src/python/python_targets:test_library_transitive_dependee_2',
                    'src/python/python_targets:test_library_transitive_dependee_3',
                    'src/python/python_targets:test_library_transitive_dependee_4'}
    expected_set = set(self.TEST_MAPPING[changed_src]['transitive']) - excluded_set

    with create_isolated_git_repo() as worktree:
      with mutated_working_copy([os.path.join(worktree, changed_src)]):
        pants_run = self.run_pants([
          '-ldebug',   # This ensures the changed target names show up in the pants output.
          '--exclude-target-regexp={}'.format(exclude_target_regexp),
          'test-changed',
          '--changes-since=HEAD',
          '--include-dependees=transitive'
        ])

      self.assert_success(pants_run)
      for expected_item in expected_set:
        self.assertIn(expected_item, pants_run.stdout_data)

      for excluded_item in excluded_set:
        self.assertNotIn(excluded_item, pants_run.stdout_data)

  @ensure_engine
  def test_changed_changed_since_and_files(self):
    with create_isolated_git_repo():
      stdout = self.assert_changed_new_equals_old(['--changed-since=HEAD^^', '--files'])

      # The output should be the files added in the last 2 commits.
      self.assertEqual(
        lines_to_set(stdout),
        {'src/python/sources/BUILD',
         'src/python/sources/sources.py',
         'src/python/sources/sources.txt',
         '3rdparty/BUILD'}
      )

  @ensure_engine
  def test_changed_diffspec_and_files(self):
    with create_isolated_git_repo():
      git_sha = subprocess.check_output(['git', 'rev-parse', 'HEAD^^']).strip()
      stdout = self.assert_changed_new_equals_old(['--changed-diffspec={}'.format(git_sha), '--files'])

      # The output should be the files added in the last 2 commits.
      self.assertEqual(
        lines_to_set(stdout),
        {'src/python/python_targets/BUILD',
         'src/python/python_targets/test_binary.py',
         'src/python/python_targets/test_library.py',
         'src/python/python_targets/test_unclaimed_src.py'}
      )

  @ensure_engine
  def test_changed_with_multiple_build_files(self):
    new_build_file = 'src/python/python_targets/BUILD.new'

    with create_isolated_git_repo() as worktree:
      touch(os.path.join(worktree, new_build_file))
      pants_run = self.run_pants(['changed'])

      self.assert_success(pants_run)
      self.assertEqual(pants_run.stdout_data.strip(), '')

  @ensure_engine
  def test_changed_with_deleted_file(self):
    deleted_file = 'src/python/sources/sources.py'

    with create_isolated_git_repo() as worktree:
      safe_delete(os.path.join(worktree, deleted_file))
      pants_run = self.run_pants(['changed'])
      self.assert_success(pants_run)
      self.assertEqual(pants_run.stdout_data.strip(), 'src/python/sources:sources')

  def test_list_changed(self):
    deleted_file = 'src/python/sources/sources.py'

    with create_isolated_git_repo() as worktree:
      safe_delete(os.path.join(worktree, deleted_file))
      pants_run = self.run_pants(['--enable-v2-engine', '--changed-parent=HEAD', 'list'])
      self.assert_success(pants_run)
      self.assertEqual(pants_run.stdout_data.strip(), 'src/python/sources:sources')

  # Following 4 tests do not run in isolated repo because they don't mutate working copy.
  def test_changed(self):
    self.assert_changed_new_equals_old([])

  @unittest.skip("Pending fix for https://github.com/pantsbuild/pants/issues/4010")
  def test_changed_with_changes_since(self):
    self.assert_changed_new_equals_old(['--changes-since=HEAD^^'])

  @unittest.skip("Pending fix for https://github.com/pantsbuild/pants/issues/4010")
  def test_changed_with_changes_since_direct(self):
    self.assert_changed_new_equals_old(['--changes-since=HEAD^^', '--include-dependees=direct'])

  @unittest.skip("Pending fix for https://github.com/pantsbuild/pants/issues/4010")
  def test_changed_with_changes_since_transitive(self):
    self.assert_changed_new_equals_old(['--changes-since=HEAD^^', '--include-dependees=transitive'])


ChangedIntegrationTest.generate_tests()
