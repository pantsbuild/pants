# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from collections import defaultdict

from pants.contrib.go.targets.go_binary import GoBinary
from pants.contrib.go.tasks.go_task import GoTask


class GoGetBinary(GoTask):

  @classmethod
  def product_types(cls):
    return ['go_binary']

  @classmethod
  def prepare(cls, options, round_manager):
    super(GoGetBinary, cls).prepare(options, round_manager)
    round_manager.require_data('go_workspace')

  @staticmethod
  def is_binary(target):
    return isinstance(target, GoBinary)

  def execute(self):
    targets = self.context.targets(self.is_binary)
    self.context.products.safe_create_data('go_binary', lambda: defaultdict(str))
    for target in targets:
      go_workspace = self.context.products.get_data('go_workspace').get(target)
      if go_workspace is None:
        raise TaskError
      binary_path = os.path.join(go_workspace, 'bin', os.path.basename(target.target_base))
      self.context.products.get_data('go_binary')[target] = binary_path
