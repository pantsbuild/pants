# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import copy

from pants.base.exceptions import TaskError

from pants.contrib.rust.utils.basic_invocation_conversion_utils import reduce_invocation
from pants.contrib.rust.utils.collector import collect_information, get_default_information
from pants.contrib.rust.utils.custom_build_invocation_conversion_rules import (args_rules,
                                                                               env_rules,
                                                                               links_rules,
                                                                               outputs_rules,
                                                                               program_rules)


def get_default_build_conversion_rules():
  return {
    'args': args_rules,
    'outputs': outputs_rules,
    'links': links_rules,
    'env': env_rules
  }


def get_default_run_conversion_rules():
  return {
    'program': program_rules,
    'env': env_rules
  }


def convert_into_pants_invocation(target, result_dir, crate_out_dirs, libraries_dir):
  pants_invocation = copy.deepcopy(target.cargo_invocation)
  information = collect_information(pants_invocation, get_default_information())
  make_dirs = dict()

  compile_mode = pants_invocation["compile_mode"]

  if compile_mode == "build":
    conversion_rules_set = get_default_build_conversion_rules()
  elif compile_mode == "run-custom-build":
    conversion_rules_set = get_default_run_conversion_rules()
  else:
    raise TaskError('Unsupported compile mode! {0}'.format(compile_mode))

  for key in pants_invocation:
    apply_rule = conversion_rules_set.get(key, None)
    if apply_rule:
      apply_rule(
        invocation_key=pants_invocation[key],
        target=target,
        result_dir=result_dir,
        crate_out_dirs=crate_out_dirs,
        libraries_dir=libraries_dir,
        information=information,
        invocation=pants_invocation,
        make_dirs=make_dirs
      )

  if compile_mode == "build":
    crate_out_dirs[target.address.target_name] = ('None', pants_invocation['links'])
  else:
    crate_out_dirs[target.address.target_name] = ('None', pants_invocation['env']['OUT_DIR'])

  pants_invocation['pants_make_dirs'] = make_dirs

  return reduce_invocation(pants_invocation)
