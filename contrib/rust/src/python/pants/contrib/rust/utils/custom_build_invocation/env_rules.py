# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os

from pants.contrib.rust.utils.basic_invocation.env_rules import dyld_lib_path_rule


def out_dir_rule(old_path, result_dir, make_dirs, **kargs):
  head, out = os.path.split(old_path)
  head, package_name = os.path.split(head)
  new_path = os.path.join(result_dir, 'build', package_name, out)
  make_dirs.add(new_path)
  return new_path


def env_rules(invocation_key, rules=None, **kargs):
  if rules is None:
    rules = {
      'OUT_DIR': out_dir_rule,
      # nightly-2018-12-31 macOS
      'DYLD_LIBRARY_PATH': dyld_lib_path_rule,
      # nightly macOS
      'DYLD_FALLBACK_LIBRARY_PATH': dyld_lib_path_rule,
      # nightly-2018-12-31 linux
      'LD_LIBRARY_PATH': dyld_lib_path_rule
    }

  for key, value in invocation_key.items():
    apply_rule = rules.get(key)
    if apply_rule:
      invocation_key[key] = apply_rule(value, **kargs)
