# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.backend.android.targets.android_binary import AndroidBinary
from pants.backend.android.tasks.aapt_task import AaptTask

class AaptBuilder(AaptTask):


  @classmethod
  def product_types(cls):
    return ['apk']

    @staticmethod
    def is_app(target):
      return isinstance(target, (AndroidBinary))

  def __init__(self, context, workdir):
    super(AaptBuilder, self).__init__(context, workdir)
    #TODO(mateor) verfify if --ignored-assets is needed in bundle process

  def prepare(self, round_manager):
    round_manager.require_data('dex')

  def execute(self):
    print ("EXECUTING")
    pass