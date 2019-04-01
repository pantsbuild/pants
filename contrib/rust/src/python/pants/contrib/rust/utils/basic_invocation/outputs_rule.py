# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os


def change_path(path, result_dir, make_dirs, make_sym_links, **kargs):
  file_name = os.path.basename(path)
  new_dir = os.path.join(result_dir, 'deps')
  make_dirs.add(new_dir)
  new_file = os.path.join(new_dir, file_name)
  make_sym_links.add(new_file)
  return new_file


def outputs_rule(invocation_key, **kargs):
  for index, path in enumerate(invocation_key):
    invocation_key[index] = change_path(path, **kargs)
