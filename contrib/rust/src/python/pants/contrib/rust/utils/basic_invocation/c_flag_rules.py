# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os


def incremental(_, result_dir, make_dirs, **kwargs):
  new_path = os.path.join(result_dir, 'incremental')
  make_dirs.add(new_path)
  return new_path
