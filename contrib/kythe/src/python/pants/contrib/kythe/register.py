# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.goal.task_registrar import TaskRegistrar as task

from pants.contrib.kythe.tasks.extract_java import ExtractJava
from pants.contrib.kythe.tasks.index_java import IndexJava


def register_goals():
  task(name='extract', action=ExtractJava).install('kythe')
  task(name='index', action=IndexJava).install('kythe')
