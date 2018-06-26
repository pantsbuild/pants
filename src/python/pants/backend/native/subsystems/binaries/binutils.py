# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.native.config.environment import Linker, Platform
from pants.binaries.binary_tool import NativeTool
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Select


class Binutils(NativeTool):
  options_scope = 'binutils'
  default_version = '2.30'
  archive_type = 'tgz'

  def path_entries(self):
    return [os.path.join(self.select(), 'bin')]

  def linker(self, platform):
    return Linker(
      path_entries=self.path_entries(),
      exe_filename='gcc',  # TODO: Change this back to 'ld' per #5943
      platform=platform)


@rule(Linker, [Select(Platform), Select(Binutils)])
def get_ld(platform, binutils):
  return binutils.linker(platform)


def create_binutils_rules():
  return [
    get_ld,
    RootRule(Binutils),
  ]
