# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.contrib.go.tasks.go_task import GoTask


class GoTest(GoTask):

  @classmethod
  def prepare(cls, options, round_manager):
    super(GoTest, cls).prepare(options, round_manager)
    round_manager.require_data('gopath')

  def execute(self):
    for target in filter(self.is_go_source, self.context.target_roots):
      gopath = self.context.products.get_data('gopath')[target]
      self.run_go_cmd('test', gopath, target)
