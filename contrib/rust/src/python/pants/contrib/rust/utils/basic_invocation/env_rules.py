# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os

from pants.contrib.rust.targets.synthetic.cargo_synthetic_custom_build import \
  CargoSyntheticCustomBuild


def out_dir_rule(old_path, target, crate_out_dirs, result_dir, **kwargs):
  if len(target.dependencies) != 0:
    for dependency in target.dependencies:
      if isinstance(dependency, CargoSyntheticCustomBuild):
        return crate_out_dirs[dependency.address.target_name][1]
  else:
    head, out = os.path.split(old_path)
    head, package_name = os.path.split(head)
    return os.path.join(result_dir, 'build', package_name, out)


def dyld_lib_path_rule(old_path, libraries_dir, **kwargs):
  user_path, system_paths = old_path.split(':', 1)
  new_path = "{}:{}".format(libraries_dir, system_paths)
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
