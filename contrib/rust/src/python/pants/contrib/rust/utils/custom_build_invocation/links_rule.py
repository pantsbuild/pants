# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import copy
import os


def change_key_value(path, result_dir, information, **kargs):
  file_name = os.path.basename(path)
  package_name = "{}{}".format(information['package_name'], information['extra-filename'])
  return os.path.join(result_dir, 'build', package_name, file_name)


def links_rule(invocation_key, **kargs):
  cache = copy.deepcopy(invocation_key)
  for key, value in cache.items():
    invocation_key.pop(key)
    invocation_key[change_key_value(key, **kargs)] = change_key_value(value, **kargs)
