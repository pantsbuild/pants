# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from mock import Mock, patch
from pants.backend.codegen.targets.java_thrift_library import JavaThriftLibrary
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants_test.tasks.task_test_base import TaskTestBase

from pants.contrib.scrooge.tasks.thrift_linter import ThriftLinter


class ThriftLinterTest(TaskTestBase):
  def _prepare_mocks(self, task):
    self._run_java_mock = Mock(return_value=0)
    task.tool_classpath = Mock(return_value='foo_classpath')
    task.runjava = self._run_java_mock

  @property
  def alias_groups(self):
    return BuildFileAliases(
      targets={
        'java_thrift_library': JavaThriftLibrary,
      },
    )

  @classmethod
  def task_type(cls):
    return ThriftLinter

  @patch('pants.contrib.scrooge.tasks.thrift_linter.calculate_compile_sources')
  def test_lint(self, mock_calculate_compile_sources):

    def get_default_jvm_options():
      return self.task_type().get_jvm_options_default(self.context().options.for_global_scope())

    thrift_target = self.create_library('a', 'java_thrift_library', 'a', ['A.thrift'])
    task = self.create_task(self.context(target_roots=thrift_target))
    self._prepare_mocks(task)
    expected_include_paths = {'src/thrift/tweet', 'src/thrift/users'}
    expected_paths = {'src/thrift/tweet/a.thrift', 'src/thrift/tweet/b.thrift'}
    mock_calculate_compile_sources.return_value = (expected_include_paths, expected_paths)
    task._lint(thrift_target)

    self._run_java_mock.assert_called_once_with(classpath='foo_classpath',
      main='com.twitter.scrooge.linter.Main',
      args=['--ignore-errors', '--include-path', 'src/thrift/users', '--include-path',
            'src/thrift/tweet', 'src/thrift/tweet/b.thrift', 'src/thrift/tweet/a.thrift'],
      jvm_options=get_default_jvm_options(),
      workunit_labels=['COMPILER'])
