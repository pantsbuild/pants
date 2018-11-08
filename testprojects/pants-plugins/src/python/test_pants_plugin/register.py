# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from test_pants_plugin.pants_infra_tests import PantsInfraTests
from test_pants_plugin.subsystems.pants_test_infra import PantsTestInfra
from test_pants_plugin.tasks.lifecycle_stub_task import LifecycleStubTask
from test_pants_plugin.tasks.thrift_preprocess_stub import ThriftPreprocessStub

from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.goal.task_registrar import TaskRegistrar as task

from pants.contrib.scrooge.tasks.thrift_linter import ThriftLinter


def build_file_aliases():
  return BuildFileAliases(
    context_aware_object_factories={
      'pants_infra_tests': PantsInfraTests,
    }
  )

def register_goals():
  task(name='lifecycle-stub-task', action=LifecycleStubTask).install('lifecycle-stub-goal')
  task(name='preprocess-stub-for-thrift', action=ThriftPreprocessStub).install('thrift-stub-goal')
  task(name='thrift-linter', action=ThriftLinter).install('lint')


def global_subsystems():
  return (PantsTestInfra,)
