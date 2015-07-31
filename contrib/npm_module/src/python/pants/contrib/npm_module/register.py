# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.build_file_aliases import BuildFileAliases
from pants.goal.task_registrar import TaskRegistrar as task

from pants.contrib.npm_module.targets.gen_resources import GenResources
from pants.contrib.npm_module.tasks.transpilers.lessc import LessC
from pants.contrib.npm_module.tasks.transpilers.requirejs import RequireJS
from pants.contrib.npm_module.tasks.transpilers.rtl import RTL


def build_file_aliases():
  # TODO: Rename this to better target once Javascript Pants design is finalized
  return BuildFileAliases.create({'generated_resources': GenResources})


def register_goals():
  task(name='lessc', action=LessC).install('gen')
  task(name='requirejs', action=RequireJS).install('gen')
  task(name='rtl', action=RTL).install('gen')