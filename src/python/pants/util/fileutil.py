# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shutil

from pants.util.contextutil import temporary_file


def atomic_copy(src, dst):
  """Copy the file src to dst, overwriting dst atomically."""
  with temporary_file(root_dir=os.path.dirname(dst)) as tmp_dst:
    shutil.copyfile(src, tmp_dst.name)
    os.rename(tmp_dst.name, dst)


def create_size_estimators():
  def line_count(filename):
    with open(filename, 'rb') as fh:
      return sum(1 for line in fh)
  return {
    'linecount': lambda srcs: sum(line_count(src) for src in srcs),
    'filecount': lambda srcs: len(srcs),
    'filesize': lambda srcs: sum(os.path.getsize(src) for src in srcs),
    'nosize': lambda srcs: 0,
  }
