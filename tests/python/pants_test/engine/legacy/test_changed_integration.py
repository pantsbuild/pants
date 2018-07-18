# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
import shutil
from builtins import str
from contextlib import contextmanager
from textwrap import dedent

from pants.base.build_environment import get_buildroot
from pants.util.contextutil import environment_as, temporary_dir
from pants.util.dirutil import safe_delete, safe_mkdir, safe_open, touch
from pants_test.base_test import TestGenerator
from pants_test.pants_run_integration_test import PantsRunIntegrationTest, ensure_daemon
from pants_test.testutils.git_util import initialize_repo


def lines_to_set(str_or_list):
  if isinstance(str_or_list, list):
    return set(str_or_list)
  else:
    return set(x for x in str(str_or_list).split('\n') if x)


def create_file_in(worktree, path, content):
  """Creates a file in the given worktree, and returns its path."""
  write_path = os.path.join(worktree, path)
  with safe_open(write_path, 'w') as f:
    f.write(dedent(content))
  return write_path


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
      return create_file_in(worktree, path, content)

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
              stdout = self.run_list(
                ['--changed-include-dependees={}'.format(dependee_type), '--changed-parent=HEAD'],
              )

              self.assertEqual(
                lines_to_set(self.TEST_MAPPING[filename][dependee_type]),
                lines_to_set(stdout)
              )

        cls.add_test(
          'test_changed_coverage_{}_{}'.format(dependee_type, safe_filename(filename)),
          inner_integration_coverage_test
        )

  def run_list(self, extra_args, success=True):
    list_args = ['-q', 'list'] + extra_args
    pants_run = self.do_command(*list_args, success=success)
    return pants_run.stdout_data

  def test_changed_exclude_root_targets_only(self):
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
          '--changed-parent=HEAD',
          '--changed-include-dependees=transitive',
          'test',
        ])

      self.assert_success(pants_run)
      for expected_item in expected_set:
        self.assertIn(expected_item, pants_run.stdout_data)

      for excluded_item in excluded_set:
        self.assertNotIn(excluded_item, pants_run.stdout_data)

  def test_changed_not_exclude_inner_targets(self):
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
          '--changed-parent=HEAD',
          '--changed-include-dependees=transitive',
          'test',
        ])

      self.assert_success(pants_run)
      for expected_item in expected_set:
        self.assertIn(expected_item, pants_run.stdout_data)

      for excluded_item in excluded_set:
        self.assertNotIn(excluded_item, pants_run.stdout_data)

  def test_changed_with_multiple_build_files(self):
    new_build_file = 'src/python/python_targets/BUILD.new'

    with create_isolated_git_repo() as worktree:
      touch(os.path.join(worktree, new_build_file))
      stdout_data = self.run_list([])
      self.assertEqual(stdout_data.strip(), '')

  def test_changed_with_deleted_source(self):
    with create_isolated_git_repo() as worktree:
      safe_delete(os.path.join(worktree, 'src/python/sources/sources.py'))
      pants_run = self.run_pants(['list', '--changed-parent=HEAD'])
      self.assert_success(pants_run)
      self.assertEqual(pants_run.stdout_data.strip(), 'src/python/sources:sources')

  def test_changed_with_deleted_resource(self):
    with create_isolated_git_repo() as worktree:
      safe_delete(os.path.join(worktree, 'src/python/sources/sources.txt'))
      pants_run = self.run_pants(['list', '--changed-parent=HEAD'])
      self.assert_success(pants_run)
      changed_targets = [
        'src/python/sources:overlapping-globs',
        'src/python/sources:some-missing-some-not',
        'src/python/sources:text',
      ]
      self.assertEqual(pants_run.stdout_data.strip(),
                       '\n'.join(changed_targets))

  def test_changed_with_deleted_target_transitive(self):
    with create_isolated_git_repo() as worktree:
      safe_delete(os.path.join(worktree, 'src/resources/org/pantsbuild/resourceonly/BUILD'))
      pants_run = self.run_pants(['list', '--changed-parent=HEAD', '--changed-include-dependees=transitive'])
      self.assert_failure(pants_run)
      self.assertIn('src/resources/org/pantsbuild/resourceonly', pants_run.stderr_data)

  def test_changed_in_directory_without_build_file(self):
    with create_isolated_git_repo() as worktree:
      create_file_in(worktree, 'new-project/README.txt', 'This is important.')
      pants_run = self.run_pants(['list', '--changed-parent=HEAD'])
      self.assert_success(pants_run)
      self.assertEqual(pants_run.stdout_data.strip(), '')

  @ensure_daemon
  def test_list_changed(self):
    deleted_file = 'src/python/sources/sources.py'

    with create_isolated_git_repo() as worktree:
      safe_delete(os.path.join(worktree, deleted_file))
      pants_run = self.run_pants(['--changed-parent=HEAD', 'list'])
      self.assert_success(pants_run)
      self.assertEqual(pants_run.stdout_data.strip(), 'src/python/sources:sources')


ChangedIntegrationTest.generate_tests()
