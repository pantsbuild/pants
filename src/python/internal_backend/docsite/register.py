# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from internal_backend.docsite.tasks.docsitegen import DocsiteGen
from pants.goal.task_registrar import TaskRegistrar as task

def register_goals():
  print("DSG.register", "register_goals") # TODO
  task(
    name='docsitegen', action=DocsiteGen
  ).install('docsitegen').with_description('')
