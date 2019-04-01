# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import copy
import os


def change_key(path, result_dir, **kargs):
  file_name = os.path.basename(path)
  return os.path.join(result_dir, file_name)


def change_value(path, result_dir, **kargs):
  file_name = os.path.basename(path)
  return os.path.join(result_dir, 'deps', file_name)


def links_rule(invocation_key, **kargs):
  cache = copy.deepcopy(invocation_key)
  for key, value in cache.items():
    invocation_key.pop(key, None)
    invocation_key[change_key(key, **kargs)] = change_value(value, **kargs)
