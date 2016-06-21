# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os

from pants.task.task import Task
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_concurrent_rename, safe_mkdir, safe_rmtree


logger = logging.getLogger(__name__)


class Clean(Task):
  """Delete all build products, creating a clean workspace.
  Speeds up run time of clean-all by moving current .pants.d to a temp folder
  and deleting it in a subprocess"""

  @classmethod
  def register_options(cls, register):
    super(Clean, cls).register_options(register)
    register('--async', type=bool, default=False,
             help='Allows clean-all to run in the background. Can dramatically speed up clean-all'
                  'for large .pants.d files.')

  def execute(self):
    # Get current pants working directory.
    pants_wd = self.get_options().pants_workdir
    if self.get_options().async:
      # Although cleanup is set to False, temp dir is still deleted in subprocess.
      with temporary_dir(cleanup=False) as tmpdir:
        pid = os.fork()

        if pid == 0:
          logger.info('Temporary directory created at {tmpdir}'.format(tmpdir=tmpdir))
          # Creates subdirectory to move contents.
          clean_dir = os.path.join(tmpdir, "clean")
          safe_mkdir(clean_dir)

          # Moves contents of .pants.d to cleanup dir.
          safe_concurrent_rename(pants_wd, clean_dir)

          # Deletes temporary dir (including old .pants.d) in subprocess.
          safe_rmtree(tmpdir)
          os._exit(0)
    else:
      # Recursively removes pants cache; user waits patiently.
      logger.info('For async removal, run `./pants clean-all --async`')
      safe_rmtree(pants_wd)
