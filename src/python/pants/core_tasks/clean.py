# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import subprocess

from pants.task.task import Task
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_concurrent_rename, safe_mkdir, safe_rmtree


class Clean(Task):
  """Delete all build products, creating a clean workspace.
  Speeds up run time of clean-all by moving current .pants.d to a temp folder
  and deleting it in a subprocess"""
  def execute(self):
    # although cleanup is set to False, temp dir is still deleted in subprocess
    with temporary_dir(cleanup=False) as tmpdir:
      # creates subdirectory to move contents to
      clean_dir = os.path.join(tmpdir, "clean")
      safe_mkdir(clean_dir)

      # moves contents of .pants.d to cleanup dir
      pants_wd = self.get_options().pants_workdir
      safe_concurrent_rename(pants_wd, clean_dir)

      # deletes temporary dir (including old .pants.d) in subprocess
      subprocess.Popen(["rm", "-rf", tmpdir])
