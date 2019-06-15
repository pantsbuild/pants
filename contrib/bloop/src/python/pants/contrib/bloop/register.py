# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.goal.task_registrar import TaskRegistrar as task

# from upstreamable.tasks.bootstrap_ensime_gen import BootstrapEnsimeGen
from pants.contrib.bloop.tasks.ensime_gen import EnsimeGen


def register_goals():
  # task(name='bootstrap-ensime-gen', action=BootstrapEnsimeGen).install('bootstrap')
  task(name='ensime-gen', action=EnsimeGen).install('ensime')
