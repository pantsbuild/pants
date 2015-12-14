# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.goal.task_registrar import TaskRegistrar as task

from pants.contrib.scalajs.targets.scala_js_binary import ScalaJSBinary
from pants.contrib.scalajs.tasks.scala_js_link import ScalaJSLink
from pants.contrib.scalajs.tasks.scala_js_zinc_compile import ScalaJSZincCompile


def build_file_aliases():
  return BuildFileAliases(
    targets={
      'scala_js_binary': ScalaJSBinary,
    },
  )

def register_goals():
  task(name='scala-js', action=ScalaJSZincCompile).install('compile')
  task(name='scala-js', action=ScalaJSLink).install('link')
