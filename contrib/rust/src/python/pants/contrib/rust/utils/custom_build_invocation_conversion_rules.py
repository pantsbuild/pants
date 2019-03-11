# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import copy
import os


def args_rules(invocation_key, target, result_dir, crate_out_dirs, libraries_dir, information,
               make_dirs, **kwargs):
  def _c_flag_rules(key_value):
    def _incremental(_):
      new_path = os.path.join(result_dir, 'incremental')
      make_dirs.add(new_path)
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
    package_name = "{}{}".format(information['package_name'], information['extra-filename'])
    new_path = os.path.join(result_dir, 'build', package_name)
    make_dirs.add(new_path)
    return new_path

  def _extern_flag_rule(key_value):
    # find in dep_dir
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


def env_rules(invocation_key, result_dir, libraries_dir, make_dirs, **kwargs):
  def _out_dir(old_path):
    head, out = os.path.split(old_path)
    head, package_name = os.path.split(head)
    new_path = os.path.join(result_dir, 'build', package_name, out)
    make_dirs.add(new_path)
    return new_path

  def _dyld_lib_path(old_path):
    user_path, system_paths = old_path.split(':', 1)
    new_path = "{}:{}".format(libraries_dir, system_paths)
    return new_path

  rules = {
    'OUT_DIR': _out_dir,
    'DYLD_LIBRARY_PATH': _dyld_lib_path
  }

  for key, value in invocation_key.items():
    apply_rule = rules.get(key, None)
    if apply_rule:
      invocation_key[key] = apply_rule(value)


def outputs_rules(invocation_key, result_dir, information, make_dirs, **kwargs):
  def _change(path, result_dir):
    file_name = os.path.basename(path)
    package_name = "{}{}".format(information['package_name'], information['extra-filename'])
    new_dir = os.path.join(result_dir, 'build', package_name)
    make_dirs.add(new_dir)
    return os.path.join(new_dir, file_name)

  for index, path in enumerate(invocation_key):
    invocation_key[index] = _change(path, result_dir)


def links_rules(invocation_key, result_dir, information, **kwargs):
  def _change(path, result_dir):
    file_name = os.path.basename(path)
    package_name = "{}{}".format(information['package_name'], information['extra-filename'])
    return os.path.join(result_dir, 'build', package_name, file_name)

  tmp_copy = copy.deepcopy(invocation_key)

  for key, value in tmp_copy.items():
    invocation_key.pop(key, None)
    invocation_key[_change(key, result_dir)] = _change(value, result_dir)


def program_rules(target, crate_out_dirs, invocation, **kwargs):
  for dependency in target.dependencies:
    package_name, links = crate_out_dirs[dependency.address.target_name]
    assert len(list(links.keys())) == 1, (
      'Cannot find build script of {target_name}'
      .format(target_name=target.address.target_name)
    )
    out_dir = list(links.keys())[0]
    # https://github.com/rust-lang/cargo/blob/245818076052dd7178f5bb7585f5aec5b6c1e03e/src/cargo/util/toml/targets.rs#L107
    if os.path.basename(out_dir).startswith('build-script-', 0, 13):
      invocation['program'] = out_dir
