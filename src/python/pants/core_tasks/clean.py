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

  The clean-all method allows for both synchronous and asynchronous options with the --async option."""

  @classmethod
  def register_options(cls, register):
    super(Clean, cls).register_options(register)
    register('--async', type=bool, default=False,
             help='Allows clean-all to run in the background. Can dramatically speed up clean-all '
                  'for large pants workdirs.')

  def execute(self):
    # Get current pants working directory. 
    pants_wd = self.get_options().pants_workdir
    pants_trash = os.path.join(pants_wd, "trash")

    # Although cleanup is set to False, temp dir is still deleted in subprocess. 
    with temporary_dir(cleanup=False, root_dir=os.path.dirname(pants_wd), prefix=".pants_cleanall") as tmpdir:
      logger.debug('Moving trash to {} for deletion'.format(tmpdir))

      # Creates subdirectory to move contents. 
      tmp_trash = os.path.join(tmpdir, "trash")
      safe_mkdir(tmp_trash)

      # Moves contents of .pants.d to cleanup dir
      safe_concurrent_rename(pants_wd, tmp_trash)
      safe_concurrent_rename(tmpdir, pants_wd)

    if self.get_options().async:
      # The temporary directory is deleted in a child process that may continue running after execution.
      pid = os.fork()
      if pid == 0:
        try:
          safe_rmtree(pants_trash)
        except (IOError, OSError):
          logger.warning("Async clean-all failed. Please try again.")
        finally:
          os._exit(0)
      else:
        logger.debug("Forked an asynchronous clean-all worker at pid: {}".format(pid))
    else:
      # Recursively removes pants cache; user waits patiently. 
      logger.info('For async removal, run `./pants clean-all --async`')
      safe_rmtree(pants_trash)
