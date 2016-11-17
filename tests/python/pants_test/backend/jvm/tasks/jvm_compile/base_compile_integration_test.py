# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from collections import defaultdict
from contextlib import contextmanager

import six

from pants.util.contextutil import temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class BaseCompileIT(PantsRunIntegrationTest):
  """
  :API: public
  """

  _EXTRA_TASK_ARGS=[]

  @contextmanager
  def do_test_compile(self, target, expected_files=None, iterations=2, expect_failure=False,
                      extra_args=None, workdir_outside_of_buildroot=False):
    """Runs a configurable number of iterations of compilation for the given target.

    :API: public

    By default, runs twice to shake out errors related to noops.
    """
    if not workdir_outside_of_buildroot:
      workdir_generator = self.temporary_workdir()
    else:
      workdir_generator = temporary_dir(suffix='.pants.d')

    with workdir_generator as workdir:
      with self.temporary_cachedir() as cachedir:
        for i in six.moves.xrange(0, iterations):
          pants_run = self.run_test_compile(workdir, cachedir, target,
                                            clean_all=(i == 0),
                                            extra_args=extra_args)
          if expect_failure:
            self.assert_failure(pants_run)
          else:
            self.assert_success(pants_run)
        found = defaultdict(set)
        workdir_files = []
        if expected_files:
          to_find = set(expected_files)
          for root, _, files in os.walk(workdir):
            for file in files:
              workdir_files.append(os.path.join(root, file))
              if file in to_find:
                found[file].add(os.path.join(root, file))
          to_find.difference_update(found)
          if not expect_failure:
            self.assertEqual(set(), to_find,
                             'Failed to find the following compiled files: {} in {}'.format(
                               to_find, '\n'.join(sorted(workdir_files))))
        yield found

  def run_test_compile(self, workdir, cacheurl, target, clean_all=False, extra_args=None, test=False):
    """
    :API: public
    """
    config = {
      'cache': {
        'write': True,
        'write_to': [cacheurl],
      },
    }
    task = 'test' if test else 'compile'
    args = self._EXTRA_TASK_ARGS + [task, target] + (extra_args if extra_args else [])
    # Clean-all on the first iteration.
    if clean_all:
      args.insert(0, 'clean-all')
    return self.run_pants_with_workdir(args, workdir, config=config)

  def get_only(self, found, name):
    files = found[name]
    self.assertEqual(1, len(files))
    return files.pop()

  def do_test_success_and_failure(self, target, success_args, failure_args, shared_args=None):
    """Ensure that a target fails to build when one arg set is passed, and succeeds for another.

    :API: public
    """
    shared_args = shared_args if shared_args else []

    # Check that success_args succeed.
    with self.do_test_compile(target, extra_args=(shared_args + success_args)):
      pass

    # Check that failure_args fail.
    with self.do_test_compile(target, extra_args=(shared_args + failure_args), expect_failure=True):
      pass
