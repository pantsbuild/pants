# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from internal_backend.sitegen.tasks.sitegen import SiteGen
from pants.goal.task_registrar import TaskRegistrar as task


def register_goals():
  task(
    name='sitegen', action=SiteGen
  ).install('sitegen').with_description('Generate static web site.')
