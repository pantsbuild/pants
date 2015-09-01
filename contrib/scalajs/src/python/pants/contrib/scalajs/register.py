# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.core.tasks.group_task import GroupTask
from pants.base.build_file_aliases import BuildFileAliases
from pants.goal.task_registrar import TaskRegistrar as task

from pants.contrib.scalajs.targets.scala_js_binary import ScalaJSBinary
from pants.contrib.scalajs.tasks.scala_js_link import ScalaJSLink
from pants.contrib.scalajs.tasks.scala_js_zinc_compile import ScalaJSZincCompile


def build_file_aliases():
  return BuildFileAliases.create(
    targets={
      'scala_js_binary': ScalaJSBinary,
    },
  )

def register_goals():
  # Compilation.
  scala_js_compile = GroupTask.named(
      'scala-js-compile',
      product_type=['scala_js_ir'],
      flag_namespace=['compile'])
  scala_js_compile.add_member(ScalaJSZincCompile)
  task(name='scala-js', action=scala_js_compile).install('compile').with_description('Compile scala source code for javascript.')

  # Link ScalaJS IR into Javascript.
  task(name='scala-js', action=ScalaJSLink).install('link').with_description('Link intermediate scala outputs to a javascript binary.')
