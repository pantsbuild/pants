# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.backend.jvm.tasks.checkstyle import Checkstyle
from pants.backend.jvm.tasks.scalastyle import Scalastyle
from pants.goal.task_registrar import TaskRegistrar as task


def register_goals():
  task(name='checkstyle', action=Checkstyle,
       dependencies=['gen', 'resolve']
  ).install('compile')

  task(name='scalastyle', action=Scalastyle,
       dependencies=['bootstrap']
  ).install('compile')
