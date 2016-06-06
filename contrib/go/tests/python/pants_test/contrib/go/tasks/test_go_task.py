# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.tasks.task_test_base import TaskTestBase

from pants.contrib.go.tasks.go_task import GoTask


class ImportOracleTest(TaskTestBase):

  class ImportTask(GoTask):
    def execute(self):
      raise NotImplementedError()

  @classmethod
  def task_type(cls):
    return cls.ImportTask

  def setUp(self):
    super(ImportOracleTest, self).setUp()
    task = self.create_task(self.context())
    self.import_oracle = task.import_oracle

  def test_go_stdlib(self):
    self.assertIn('archive/tar', self.import_oracle.go_stdlib)
    self.assertIn('bufio', self.import_oracle.go_stdlib)
    self.assertIn('fmt', self.import_oracle.go_stdlib)
    self.assertNotIn('C', self.import_oracle.go_stdlib)
    self.assertNotIn('github.com/bitly/go-simplejson', self.import_oracle.go_stdlib)
    self.assertNotIn('local/pkg', self.import_oracle.go_stdlib)

  def test_is_go_internal_import(self):
    self.assertTrue(self.import_oracle.is_go_internal_import('archive/tar'))
    self.assertTrue(self.import_oracle.is_go_internal_import('bufio'))
    self.assertTrue(self.import_oracle.is_go_internal_import('fmt'))
    self.assertTrue(self.import_oracle.is_go_internal_import('C'))
    self.assertFalse(self.import_oracle.is_go_internal_import('github.com/bitly/go-simplejson'))
    self.assertFalse(self.import_oracle.is_go_internal_import('local/pkg'))

  def test_list_imports(self):
    import_listing = self.import_oracle.list_imports('archive/tar')

    self.assertEqual('tar', import_listing.pkg_name)

    self.assertTrue(len(import_listing.imports) > 0,
                    'Expected the `archive/tar` package to have at least one import')
    self.assertTrue(set(import_listing.imports).issubset(self.import_oracle.go_stdlib),
                    'All imports for any stdlib package should also be internal to the stdlib')

    self.assertTrue(len(import_listing.test_imports) > 0,
                    'Expected the `archive/tar` package to have at least 1 test that has an import')
    self.assertTrue(set(import_listing.test_imports).issubset(self.import_oracle.go_stdlib),
                    'All imports for any stdlib package (including its tests) should also be '
                    'internal to the stdlib')

  def test_is_remote_import(self):
    def is_remote(import_path):
      return self.import_oracle.is_remote_import(import_path)

    self.assertTrue(is_remote('bitbucket.com/user/project'))
    self.assertTrue(is_remote('github.com/user/project'))
    self.assertTrue(is_remote('something.com/'))
    self.assertTrue(is_remote('gopkg.in/yaml.v1'))

    self.assertFalse(is_remote('fmt'))
    self.assertFalse(is_remote('foo/bar'))
    self.assertFalse(is_remote('foo/bar.baz'))
    self.assertFalse(is_remote('.foo'))
    self.assertFalse(is_remote('.foo/bar'))
    self.assertFalse(is_remote('./foo'))
    self.assertFalse(is_remote('./foo.com'))
    self.assertFalse(is_remote('../foo.com'))
    self.assertFalse(is_remote('foo/...'))
