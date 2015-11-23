# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.goal.task_registrar import TaskRegistrar as task

from pants.contrib.node.targets.node_module import NodeModule
from pants.contrib.node.targets.node_preinstalled_module import NodePreinstalledModule
from pants.contrib.node.targets.node_remote_module import NodeRemoteModule
from pants.contrib.node.targets.node_test import NodeTest as NodeTestTarget
from pants.contrib.node.tasks.node_repl import NodeRepl
from pants.contrib.node.tasks.node_resolve import NodeResolve
from pants.contrib.node.tasks.node_run import NodeRun
from pants.contrib.node.tasks.node_test import NodeTest as NodeTestTask


def build_file_aliases():
  return BuildFileAliases(
    targets={
      'node_module': NodeModule,
      'node_preinstalled_module': NodePreinstalledModule,
      'node_remote_module': NodeRemoteModule,
      'node_test': NodeTestTarget,
    },
  )


def register_goals():
  task(name='node', action=NodeRepl).install('repl')
  task(name='node', action=NodeResolve).install('resolve')
  task(name='node', action=NodeRun).install('run')
  task(name='node', action=NodeTestTask).install('test')
