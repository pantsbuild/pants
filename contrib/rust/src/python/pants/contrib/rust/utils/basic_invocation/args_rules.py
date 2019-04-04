# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os

from pants.contrib.rust.utils.basic_invocation.c_flag_rules import incremental
from pants.contrib.rust.utils.basic_invocation.l_flag_rules import dependency as dependency_rule


def c_flag_rules(key_value, rules=None, **kwargs):
  if rules is None:
    rules = {
        'incremental': incremental,
    }

  is_key_value = key_value.split('=')

  if len(is_key_value) == 2:
    key, value = is_key_value
    apply_rule = rules.get(key)
    return ("{}={}".format(key, apply_rule(value, **kwargs))) if apply_rule else key_value
  else:
    return key_value


def l_flag_rules(key_value, rules=None, **kwargs):
  if rules is None:
    rules = {
        'dependency': dependency_rule,
    }

  is_key_value = key_value.split('=')

  if len(is_key_value) == 2:
    key, value = is_key_value
    apply_rule = rules.get(key)
    return ("{}={}".format(key, apply_rule(value, **kwargs))) if apply_rule else key_value
  else:
    return key_value


def out_dir_flag_rule(_, result_dir, make_dirs, **kwargs):
  new_path = os.path.join(result_dir, 'deps')
  make_dirs.add(new_path)
  return new_path


def extern_flag_rule(key_value, target, crate_out_dirs, **kwargs):
  key, value = key_value.split('=')

  extern = None
  for dependency in target.dependencies:
    if crate_out_dirs.get(dependency.address.target_name):
      package_name, out_dir = crate_out_dirs[dependency.address.target_name]
      if key == package_name:
        assert (len(out_dir) == 1)
        extern = "{}={}".format(key, out_dir[0])

  assert (extern is not None)

  return extern


def args_rules(invocation_key, rules=None, **kwargs):
  if rules is None:
    rules = {
        '--out-dir': out_dir_flag_rule,
        '-C': c_flag_rules,
        '-L': l_flag_rules,
        '--extern': extern_flag_rule
    }

  for index, arg in enumerate(invocation_key):
    apply_rule = rules.get(arg)
    if apply_rule:
      invocation_key[index + 1] = apply_rule(invocation_key[index + 1], **kwargs)
