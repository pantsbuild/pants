# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os

from pants.contrib.rust.utils.basic_invocation.args_rules import (c_flag_rules, extern_flag_rule,
                                                                  l_flag_rules)


def out_dir_flag_rule(_, information, result_dir, make_dirs, **kwargs):
  package_name = "{}{}".format(information['package_name'], information['extra-filename'])
  new_path = os.path.join(result_dir, 'build', package_name)
  make_dirs.add(new_path)
  return new_path


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
