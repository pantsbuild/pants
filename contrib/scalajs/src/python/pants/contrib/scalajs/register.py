# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.core.tasks.group_task import GroupTask
from pants.base.build_file_aliases import BuildFileAliases
from pants.goal.task_registrar import TaskRegistrar as task

from pants.contrib.scalajs.targets.scala_js_binary import ScalaJSBinary
from pants.contrib.scalajs.targets.scala_js_library import ScalaJSLibrary
from pants.contrib.scalajs.tasks.scala_js_link import ScalaJSLink
from pants.contrib.scalajs.tasks.scala_js_zinc_compile import ScalaJSZincCompile


def build_file_aliases():
  return BuildFileAliases.create(
    targets={
      'scala_js_binary': ScalaJSBinary,
      'scala_js_library': ScalaJSLibrary,
    },
  )

def register_goals():
  # Find the jvm-compile GroupTask (TODO: assert that it already existed and/or avoid the
  # copy-pasta here) and insert the ScalaJSZincCompile task at the front.
  jvm_compile = GroupTask.named(
      'jvm-compilers',
      product_type=['classes_by_target', 'classes_by_source'],
      flag_namespace=['compile'])
  jvm_compile.add_member(ScalaJSZincCompile, first=True)

  # Link ScalaJS IR into Javascript.
  task(name='scala-js', action=ScalaJSLink).install('link').with_description('Link intermediate outputs.')
