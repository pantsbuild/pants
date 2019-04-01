# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os


def change_path(path, result_dir, information, make_dirs, **kargs):
  file_name = os.path.basename(path)
  package_name = "{}{}".format(information['package_name'], information['extra-filename'])
  new_dir = os.path.join(result_dir, 'build', package_name)
  make_dirs.add(new_dir)
  return os.path.join(new_dir, file_name)


def outputs_rule(invocation_key, **kargs):
  for index, path in enumerate(invocation_key):
    invocation_key[index] = change_path(path, **kargs)
