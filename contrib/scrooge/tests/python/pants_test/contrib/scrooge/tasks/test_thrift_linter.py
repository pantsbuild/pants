# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from unittest.mock import Mock, patch

from pants.backend.codegen.thrift.java.java_thrift_library import JavaThriftLibrary
from pants.base.workunit import WorkUnitLabel
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.testutil.task_test_base import TaskTestBase

from pants.contrib.scrooge.tasks.thrift_linter_task import ThriftLinterTask


class ThriftLinterTest(TaskTestBase):
    def _prepare_mocks(self, task):
        self._run_java_mock = Mock(return_value=0)
        task.tool_classpath = Mock(return_value="foo_classpath")
        task.runjava = self._run_java_mock

    @classmethod
    def alias_groups(cls):
        return BuildFileAliases(targets={"java_thrift_library": JavaThriftLibrary})

    @classmethod
    def task_type(cls):
        return ThriftLinterTask

    @patch("pants.contrib.scrooge.tasks.thrift_linter_task.calculate_include_paths")
    def test_lint(self, mock_calculate_include_paths):
        def get_default_jvm_options():
            return self.task_type().get_jvm_options_default(
                self.context().options.for_global_scope()
            )

        thrift_target = self.create_library(
            path="src/thrift/tweet",
            target_type="java_thrift_library",
            name="a",
            sources=["A.thrift"],
        )
        task = self.create_task(self.context(target_roots=thrift_target))
        self._prepare_mocks(task)
        expected_include_paths = ["src/thrift/users", "src/thrift/tweet"]
        mock_calculate_include_paths.return_value = expected_include_paths
        task._lint(thrift_target, task.tool_classpath("scrooge-linter"))

        self._run_java_mock.assert_called_once_with(
            classpath="foo_classpath",
            main="com.twitter.scrooge.linter.Main",
            args=[
                "--warnings",
                "--include-path",
                "src/thrift/users",
                "--include-path",
                "src/thrift/tweet",
                "src/thrift/tweet/A.thrift",
            ],
            jvm_options=get_default_jvm_options(),
            workunit_labels=[WorkUnitLabel.COMPILER, WorkUnitLabel.SUPPRESS_LABEL],
        )

    @patch("pants.contrib.scrooge.tasks.thrift_linter_task.calculate_include_paths")
    def test_lint_direct_only(self, mock_calculate_include_paths):
        # Validate that we do lint only the direct sources of a target, rather than including the
        # sources of its transitive deps.

        def get_default_jvm_options():
            return self.task_type().get_jvm_options_default(
                self.context().options.for_global_scope()
            )

        self.create_library(
            path="src/thrift/tweet",
            target_type="java_thrift_library",
            name="a",
            sources=["A.thrift"],
        )
        target_b = self.create_library(
            path="src/thrift/tweet",
            target_type="java_thrift_library",
            name="b",
            sources=["B.thrift"],
            dependencies=[":a"],
        )
        task = self.create_task(self.context(target_roots=target_b))
        self._prepare_mocks(task)
        mock_calculate_include_paths.return_value = ["src/thrift/tweet"]
        task._lint(target_b, task.tool_classpath("scrooge-linter"))

        # Confirm that we did not include the sources of the dependency.
        self._run_java_mock.assert_called_once_with(
            classpath="foo_classpath",
            main="com.twitter.scrooge.linter.Main",
            args=["--warnings", "--include-path", "src/thrift/tweet", "src/thrift/tweet/B.thrift"],
            jvm_options=get_default_jvm_options(),
            workunit_labels=[WorkUnitLabel.COMPILER, WorkUnitLabel.SUPPRESS_LABEL],
        )
