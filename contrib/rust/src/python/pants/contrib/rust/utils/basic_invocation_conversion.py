# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import copy

from pants.contrib.rust.tasks.cargo_task import CargoTask
from pants.contrib.rust.utils.basic_invocation_conversion_rules import (args_rules, env_rules,
                                                                        links_rules, outputs_rules)
from pants.contrib.rust.utils.basic_invocation_conversion_utils import (reduce_invocation,
                                                                        sanitize_crate_name)
from pants.contrib.rust.utils.collector import (collect_information, get_default_information,
                                                get_test_target_information)


def get_default_conversion_rules():
  return {
    'args': args_rules,
    'outputs': outputs_rules,
    'links': links_rules,
    'env': env_rules
  }


def convert_into_pants_invocation(target, result_dir, crate_out_dirs, libraries_dir):
  pants_invocation = copy.deepcopy(target.cargo_invocation)
  make_dirs = []
  make_sym_links = []

  transformation_rules = get_default_conversion_rules()

  for key in pants_invocation:
    apply_rule = transformation_rules.get(key, None)
    if apply_rule:
      apply_rule(
        invocation_key=pants_invocation[key],
        target=target,
        result_dir=result_dir,
        crate_out_dirs=crate_out_dirs,
        libraries_dir=libraries_dir,
        make_dirs=make_dirs,
        make_sym_links=make_sym_links,
      )

  # package_name and crate_name can be different and create_name is used in the rustc flag '--extern <create_name>=<Path>'
  information = collect_information(pants_invocation, get_default_information())
  crate_name = sanitize_crate_name(information['crate_name'])
  crate_out_dirs[target.address.target_name] = (crate_name, pants_invocation['outputs'])

  if CargoTask.is_cargo_project_test(target):
    test_cwd = collect_information(pants_invocation, get_test_target_information())
    pants_invocation['cwd_test'] = test_cwd['CARGO_MANIFEST_DIR']

  pants_invocation['pants_make_dirs'] = make_dirs
  pants_invocation['pants_make_sym_links'] = make_sym_links

  return reduce_invocation(pants_invocation)
