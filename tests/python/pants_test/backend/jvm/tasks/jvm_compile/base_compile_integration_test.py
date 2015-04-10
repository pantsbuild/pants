# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from collections import defaultdict
from contextlib import contextmanager

from pants.util.contextutil import temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class BaseCompileIT(PantsRunIntegrationTest):
  @contextmanager
  def do_test_compile(self, target, strategy, expected_files=None):
    with temporary_dir(root_dir=self.workdir_root()) as workdir:
      args = [
          'clean-all',
          'compile',
          '--compile-apt-strategy={}'.format(strategy),
          '--compile-java-strategy={}'.format(strategy),
          '--compile-scala-strategy={}'.format(strategy),
          target,
        ]
      pants_run = self.run_pants_with_workdir(args, workdir)
      self.assert_success(pants_run)
      if expected_files:
        to_find = set(expected_files)
        found = defaultdict(set)
        for root, _, files in os.walk(workdir):
          for file in files:
            if file in to_find:
              found[file].add(os.path.join(root, file))
        to_find.difference_update(found)
        self.assertEqual(set(), to_find,
                         'Failed to find the following compiled files: {}'.format(to_find))
        yield found

  def get_only(self, found, name):
    files = found[name]
    self.assertEqual(1, len(files))
    return files.pop()
