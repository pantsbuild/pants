# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import copy
import os

from pants.contrib.rust.targets.cargo_synthetic_custom_build import CargoSyntheticCustomBuild


def args_rules(invocation_key, target, result_dir, crate_out_dirs, libraries_dir, make_dirs,
               **kwargs):
  def _c_flag_rules(key_value):
    def _incremental(_):
      new_path = os.path.join(result_dir, 'incremental')
      make_dirs.append(new_path)
      return new_path

    rules = {
      'incremental': _incremental,
    }

    is_key_value = key_value.split('=')

    if len(is_key_value) == 2:
      key, value = is_key_value
      apply_rule = rules.get(key)
      return ("{}={}".format(key, apply_rule(value))) if apply_rule else key_value
    else:
      return key_value

  def _l_flag_rules(key_value):
    def dependency(_):
      return libraries_dir

    rules = {
      'dependency': dependency,
    }

    is_key_value = key_value.split('=')

    if len(is_key_value) == 2:
      key, value = is_key_value
      apply_rule = rules.get(key)
      return ("{}={}".format(key, apply_rule(value))) if apply_rule else key_value
    else:
      return key_value

  def _out_dir_flag_rule(_):
    new_path = os.path.join(result_dir, 'deps')
    make_dirs.append(new_path)
    return new_path

  def _extern_flag_rule(key_value):
    key, value = key_value.split('=')

    for dependency in target.dependencies:
      package_name, out_dir = crate_out_dirs[dependency.address.target_name]
      if key == package_name:
        return "{}={}".format(key, out_dir[0])

    return key_value

  rules = {
    '--out-dir': _out_dir_flag_rule,
    '-C': _c_flag_rules,
    '-L': _l_flag_rules,
    '--extern': _extern_flag_rule
  }

  for index, arg in enumerate(invocation_key):
    apply_rule = rules.get(arg, None)
    if apply_rule:
      invocation_key[index + 1] = apply_rule(invocation_key[index + 1])


def env_rules(invocation_key, target, result_dir, crate_out_dirs, libraries_dir, **kargs):
  def _out_dir_rule(old_path):
    if len(target.dependencies) != 0:
      for dependency in target.dependencies:
        if isinstance(dependency, CargoSyntheticCustomBuild):
          return crate_out_dirs[dependency.address.target_name][1]
    else:
      head, out = os.path.split(old_path)
      head, package_name = os.path.split(head)
      return os.path.join(result_dir, 'build', package_name, out)

  def _dyld_lib_path_rule(old_path):
    user_path, system_paths = old_path.split(':', 1)
    new_path = "{}:{}".format(libraries_dir, system_paths)
    return new_path

  rules = {
    'OUT_DIR': _out_dir_rule,
    'DYLD_LIBRARY_PATH': _dyld_lib_path_rule
  }

  for key, value in invocation_key.items():
    apply_rule = rules.get(key, None)
    if apply_rule:
      invocation_key[key] = apply_rule(value)


def outputs_rules(invocation_key, result_dir, make_dirs, make_sym_links, **kargs):
  def _change_path(path, result_dir):
    file_name = os.path.basename(path)
    new_dir = os.path.join(result_dir, 'deps')
    make_dirs.append(new_dir)
    new_file = os.path.join(new_dir, file_name)
    make_sym_links.append(new_file)
    return new_file

  for index, path in enumerate(invocation_key):
    invocation_key[index] = _change_path(path, result_dir)


def links_rules(invocation_key, result_dir, **kargs):
  def _change_key(path, result_dir):
    file_name = os.path.basename(path)
    return os.path.join(result_dir, file_name)

  def _change_value(path, result_dir):
    file_name = os.path.basename(path)
    return os.path.join(result_dir, 'deps', file_name)

  cache = copy.deepcopy(invocation_key)

  for key, value in cache.items():
    invocation_key.pop(key, None)
    invocation_key[_change_key(key, result_dir)] = _change_value(value, result_dir)
