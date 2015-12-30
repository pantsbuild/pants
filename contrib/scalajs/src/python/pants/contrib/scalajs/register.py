# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.goal.task_registrar import TaskRegistrar as task

from pants.contrib.node.tasks.node_resolve import NodeResolve
from pants.contrib.scalajs.subsystems.scala_js_platform import ScalaJSPlatform
from pants.contrib.scalajs.targets.scala_js_binary import ScalaJSBinary
from pants.contrib.scalajs.targets.scala_js_library import ScalaJSLibrary
from pants.contrib.scalajs.tasks.scala_js_link import ScalaJSLink
from pants.contrib.scalajs.tasks.scala_js_zinc_compile import ScalaJSZincCompile


def build_file_aliases():
  return BuildFileAliases(
    targets={
      'scala_js_binary': ScalaJSBinary,
      'scala_js_library': ScalaJSLibrary,
    },
  )


def register_goals():
  NodeResolve.register_resolver_for_type(ScalaJSBinary, ScalaJSPlatform)
  # NB: These task/goal assignments are pretty nuts, but are necessary in order to
  # prevent product-graph cycles between the JVM and node.js.
  #   see https://github.com/pantsbuild/pants/labels/engine
  task(name='scala-js-compile', action=ScalaJSZincCompile).install('resolve')
  task(name='scala-js-link', action=ScalaJSLink).install('resolve')


def global_subsystems():
  return {ScalaJSPlatform}
