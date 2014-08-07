# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.backend.android.tasks.aapt_task import AaptTask

class AaptBuilder(AaptTask):

  def __init__(self, context, workdir):
    super(AaptBuilder, self).__init__(context, workdir)
    print ("_WE_ _ARE_ FRA-MALY!")

  def prepare(self, round_manager):
    round_manager.require_data('dex')
  def execute(self):
    print ("EXECUTING")
    pass