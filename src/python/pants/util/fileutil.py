# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
import shutil

from pants.util.contextutil import temporary_file


def atomic_copy(src, dst):
  """Copy the file src to dst, overwriting dst atomically."""
  with temporary_file(root_dir=os.path.dirname(dst)) as tmp_dst:
    shutil.copyfile(src, tmp_dst.name)
    os.rename(tmp_dst.name, dst)
