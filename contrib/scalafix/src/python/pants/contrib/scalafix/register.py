# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.goal.task_registrar import TaskRegistrar as task

from pants.contrib.scalafix.tasks.scalafix import ScalaFixFix, ScalaFixCheck


def register_goals():
  task(name='scalafix', action=ScalaFixCheck).install('lint')
  task(name='scalafix', action=ScalaFixFix).install('fmt')
