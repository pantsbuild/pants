# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from collections import defaultdict

from pants.base.exceptions import TaskError
from pants.process.xargs import Xargs

from pants.contrib.go.tasks.go_task import GoTask


class GoCompile(GoTask):

  @classmethod
  def prepare(cls, options, round_manager):
    super(GoCompile, cls).prepare(options, round_manager)
    round_manager.require_data('gopath')

  @classmethod
  def product_types(cls):
    return ['go_binary']

  def execute(self):
    targets = self.context.targets(self.is_go_source)
    self.context.products.safe_create_data('go_binary', lambda: defaultdict(str))
    for target in self.context.target_roots:
      gopath = self.context.products.get_data('gopath')[target]
      self.run_go_cmd('install', gopath, target)
      if self.is_binary(target):
        binary_path = os.path.join(gopath, 'bin', os.path.basename(target.target_base))
        self.context.products.get_data('go_binary')[target] = binary_path
