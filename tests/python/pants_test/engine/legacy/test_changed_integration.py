# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from contextlib import contextmanager

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


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


def sort_lines(str_or_list):
  if isinstance(str_or_list, list):
    return '\n'.join(sorted(str_or_list))
  else:
    return '\n'.join(sorted(x for x in str(str_or_list).split('\n') if x))


class ChangedIntegrationTest(PantsRunIntegrationTest):

  TEST_MAPPING = {
    # A `jvm_binary` with `source='file.name'`.
    'testprojects/src/java/org/pantsbuild/testproject/utf8proto/ExampleUtf8Proto.java': dict(
      none=['testprojects/src/java/org/pantsbuild/testproject/utf8proto:utf8proto'],
      direct=['testprojects/src/java/org/pantsbuild/testproject/utf8proto:utf8proto'],
      transitive=['testprojects/src/java/org/pantsbuild/testproject/utf8proto:utf8proto']
    ),
    # A `python_binary` with `source='file.name'`.
    'testprojects/src/python/python_targets/test_binary.py': dict(
      none=['testprojects/src/python/python_targets:test'],
      direct=['testprojects/src/python/python_targets:test'],
      transitive=['testprojects/src/python/python_targets:test']
    ),
    # A `python_library` with `sources=['file.name']`.
    'testprojects/src/python/python_targets/test_library.py': dict(
      none=['testprojects/src/python/python_targets:test_library'],
      direct=['testprojects/src/python/python_targets:test',
              'testprojects/src/python/python_targets:test_library',
              'testprojects/src/python/python_targets:test_library_direct_dependee'],
      transitive=['testprojects/src/python/python_targets:test',
                  'testprojects/src/python/python_targets:test_library',
                  'testprojects/src/python/python_targets:test_library_direct_dependee',
                  'testprojects/src/python/python_targets:test_library_transitive_dependee']
    ),
    # A `resources` target with `sources=['file.name']` referenced by a `java_library` target.
    'testprojects/src/resources/org/pantsbuild/testproject/idearesourcesonly/README.md': dict(
      none=['testprojects/src/resources/org/pantsbuild/testproject/idearesourcesonly:resource'],
      direct=['testprojects/src/java/org/pantsbuild/testproject/idearesourcesonly/code:code',
              'testprojects/src/resources/org/pantsbuild/testproject/idearesourcesonly:resource'],
      transitive=['testprojects/src/java/org/pantsbuild/testproject/idearesourcesonly/code:code',
                  'testprojects/src/resources/org/pantsbuild/testproject/idearesourcesonly:resource'],
    ),
    # A `python_library` with `resources=['file.name']`.
    'testprojects/src/python/sources/sources.txt': dict(
      none=['testprojects/src/python/sources:sources'],
      direct=['testprojects/src/python/sources:sources'],
      transitive=['testprojects/src/python/sources:sources']
    ),
    # A `scala_library` with `sources=['file.name']`.
    'testprojects/tests/scala/org/pantsbuild/testproject/cp-directories/ClasspathDirectories.scala': dict(
      none=['testprojects/tests/scala/org/pantsbuild/testproject/cp-directories:cp-directories'],
      direct=['testprojects/tests/scala/org/pantsbuild/testproject/cp-directories:cp-directories'],
      transitive=['testprojects/tests/scala/org/pantsbuild/testproject/cp-directories:cp-directories']
    )
  }

  def assert_changed_new_equals_old(self, extra_args, success=True):
    args = ['-q', 'changed'] + extra_args
    normal_run = self.do_command(*args, success=success, enable_v2_engine=False)
    engine_run = self.do_command(*args, success=success, enable_v2_engine=True)
    self.assertEqual(normal_run.stdout_data, engine_run.stdout_data)
    return normal_run.stdout_data

  def test_changed(self):
    self.assert_changed_new_equals_old([])

  def test_changed_with_changes_since(self):
    self.assert_changed_new_equals_old(['--changes-since=HEAD^^'])

  def test_changed_with_changes_since_direct(self):
    self.assert_changed_new_equals_old(['--changes-since=HEAD^^', '--include-dependees=direct'])

  def test_changed_with_changes_since_transitive(self):
    self.assert_changed_new_equals_old(['--changes-since=HEAD^^', '--include-dependees=transitive'])

  @classmethod
  def generate_changed_coverage_tests(cls):
    """Generates tests on the class for better reporting granularity than an opaque for loop test."""
    def safe_filename(f):
      return f.replace('/', '_').replace('.', '_')

    for filename in cls.TEST_MAPPING.keys():
      for dependee_type in ('none', 'direct', 'transitive'):
        def inner_integration_coverage_test(self, filename=filename, dependee_type=dependee_type):
          # Mutate the working copy so we can do `--changed-parent=HEAD` deterministically.
          with mutated_working_copy([filename]):
            stdout = self.assert_changed_new_equals_old(
              ['--changed-include-dependees={}'.format(dependee_type), '--changed-parent=HEAD']
            )

            self.assertEqual(
              sort_lines(self.TEST_MAPPING[filename][dependee_type]),
              sort_lines(stdout)
            )

        setattr(
          cls,
          'test_changed_coverage_{}_{}'.format(dependee_type, safe_filename(filename)),
          inner_integration_coverage_test
        )


ChangedIntegrationTest.generate_changed_coverage_tests()
