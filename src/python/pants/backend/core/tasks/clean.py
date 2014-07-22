# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
import time

import daemon

from pants.backend.core.tasks.console_task import ConsoleTask
from pants.base.build_environment import get_buildroot
from pants.base.config import Config
from pants.base.exceptions import TaskError
from pants.util.dirutil import safe_rmtree


def _cautious_rmtree(root):
  real_buildroot = os.path.realpath(os.path.abspath(get_buildroot()))
  real_root = os.path.realpath(os.path.abspath(root))
  if not real_root.startswith(real_buildroot):
    raise TaskError('DANGER: Attempting to delete %s, which is not under the build root!')
  safe_rmtree(real_root)


def _async_cautious_rmtree(root):
  if os.path.exists(root):
    new_path = root + '.deletable.%f' % time.time()
    os.rename(root, new_path)
    with daemon.DaemonContext():
      _cautious_rmtree(new_path)


class Invalidator(ConsoleTask):
  """Invalidate the entire build."""
  def execute(self):
    build_invalidator_dir = os.path.join(
      self.context.config.get_option(Config.DEFAULT_PANTS_WORKDIR), 'build_invalidator')
    _cautious_rmtree(build_invalidator_dir)


class Cleaner(ConsoleTask):
  """Clean all current build products."""
  def execute(self):
    _cautious_rmtree(self.context.config.getdefault('pants_workdir'))


# TODO(benjy): Do we need this? It's never been that useful, because building while
# cleaning the renamed workdir taxes the filesystem.
class AsyncCleaner(ConsoleTask):
  """Clean all current build products in a background process."""
  def execute(self):
    _async_cautious_rmtree(self.context.config.getdefault('pants_workdir'))

