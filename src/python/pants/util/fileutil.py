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
