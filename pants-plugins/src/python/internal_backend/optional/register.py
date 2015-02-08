# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.tasks.checkstyle import Checkstyle
from pants.backend.jvm.tasks.scalastyle import Scalastyle
from pants.goal.task_registrar import TaskRegistrar as task


def register_goals():
  task(name='checkstyle', action=Checkstyle).install('compile')
  task(name='scalastyle', action=Scalastyle).install('compile')
