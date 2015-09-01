# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.build_file_aliases import BuildFileAliases
from pants.goal.task_registrar import TaskRegistrar as task

from pants.contrib.node.targets.node_module import NodeModule
from pants.contrib.node.targets.node_remote_module import NodeRemoteModule
from pants.contrib.node.tasks.npm_resolve import NpmResolve


def build_file_aliases():
  return BuildFileAliases.create(
    targets={
      'node_module': NodeModule,
      'node_remote_module': NodeRemoteModule,
    },
  )


def register_goals():
  task(name='npm', action=NpmResolve).install('resolve')
