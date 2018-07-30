# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import errno
import os
import random
import shutil
from uuid import uuid4

from pants.util.contextutil import temporary_file


def atomic_copy(src, dst):
  """Copy the file src to dst, overwriting dst atomically."""
  with temporary_file(root_dir=os.path.dirname(dst)) as tmp_dst:
    shutil.copyfile(src, tmp_dst.name)
    os.chmod(tmp_dst.name, os.stat(src).st_mode)
    os.rename(tmp_dst.name, dst)


def create_size_estimators():
  """Create a dict of name to a function that returns an estimated size for a given target.

  The estimated size is used to build the largest targets first (subject to dependency constraints).
  Choose 'random' to choose random sizes for each target, which may be useful for distributed
  builds.
  :returns: Dict of a name to a function that returns an estimated size.
  """
  def line_count(filename):
    with open(filename, 'rb') as fh:
      return sum(1 for line in fh)
  return {
    'linecount': lambda srcs: sum(line_count(src) for src in srcs),
    'filecount': lambda srcs: len(srcs),
    'filesize': lambda srcs: sum(os.path.getsize(src) for src in srcs),
    'nosize': lambda srcs: 0,
    'random': lambda srcs: random.randint(0, 10000),
  }


def safe_hardlink_or_copy(source, dest, overwrite=False):
  def do_copy():
    temp_dest = dest + uuid4().hex
    shutil.copyfile(source, temp_dest)
    os.rename(temp_dest, dest)

  try:
    os.link(source, dest)
  except OSError as e:
    if e.errno == errno.EEXIST:
      # File already exists.  If overwrite=True, write otherwise skip.
      if overwrite:
        do_copy()
    elif e.errno == errno.EXDEV:
      # Hard link across devices, fall back on copying
      do_copy()
    else:
      raise
