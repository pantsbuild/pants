# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os


def program_rule(target, crate_out_dirs, invocation, **kwargs):
  for dependency in target.dependencies:
    _, links = crate_out_dirs[dependency.address.target_name]
    assert len(list(links.keys())) == 1, ('Cannot find build script of {target_name}'.format(
        target_name=target.address.target_name))
    out_dir = list(links.keys())[0]
    # https://github.com/rust-lang/cargo/blob/245818076052dd7178f5bb7585f5aec5b6c1e03e/src/cargo/util/toml/targets.rs#L107
    if os.path.basename(out_dir).startswith('build-script-', 0, 13):
      invocation['program'] = out_dir
