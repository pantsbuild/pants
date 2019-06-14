# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.goal.task_registrar import TaskRegistrar as task

from pants.contrib.node.subsystems.resolvers.node_preinstalled_module_resolver import \
  NodePreinstalledModuleResolver
from pants.contrib.node.subsystems.resolvers.npm_resolver import NpmResolver
from pants.contrib.node.targets.node_bundle import NodeBundle
from pants.contrib.node.targets.node_module import NodeModule
from pants.contrib.node.targets.node_preinstalled_module import NodePreinstalledModule
from pants.contrib.node.targets.node_remote_module import NodeRemoteModule
from pants.contrib.node.targets.node_test import NodeTest as NodeTestTarget
from pants.contrib.node.tasks.javascript_style import JavascriptStyleFmt, JavascriptStyleLint
from pants.contrib.node.tasks.node_build import NodeBuild
from pants.contrib.node.tasks.node_bundle import NodeBundle as NodeBundleTask
from pants.contrib.node.tasks.node_install import NodeInstall
from pants.contrib.node.tasks.node_repl import NodeRepl
from pants.contrib.node.tasks.node_resolve import NodeResolve
from pants.contrib.node.tasks.node_run import NodeRun
from pants.contrib.node.tasks.node_test import NodeTest as NodeTestTask


def build_file_aliases():
  return BuildFileAliases(
    targets={
      'node_bundle': NodeBundle,
      'node_module': NodeModule,
      'node_preinstalled_module': NodePreinstalledModule,
      'node_remote_module': NodeRemoteModule,
      'node_test': NodeTestTarget,
    },
  )


def register_goals():
  # Register tasks.
  task(name='node', action=NodeRepl).install('repl')
  task(name='node', action=NodeResolve).install('resolve')
  task(name='node', action=NodeRun).install('run')
  task(name='node', action=NodeBuild).install('compile', first=True)
  task(name='node', action=NodeTestTask).install('test')
  task(name='node', action=NodeBundleTask).install('bundle')
  task(name='node-install', action=NodeInstall).install()
  # Linting
  task(name='javascriptstyle', action=JavascriptStyleLint).install('lint')
  task(name='javascriptstyle', action=JavascriptStyleFmt).install('fmt')


def global_subsystems():
  return (NodePreinstalledModuleResolver, NpmResolver)
