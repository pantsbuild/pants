# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os

from pants.backend.native.config.environment import Assembler, Linker
from pants.binaries.binary_tool import NativeTool
from pants.engine.rules import rule
from pants.engine.selectors import Select


class Binutils(NativeTool):
  options_scope = 'binutils'
  default_version = '2.30'
  archive_type = 'tgz'

  def path_entries(self):
    return [os.path.join(self.select(), 'bin')]

  def assembler(self):
    return Assembler(
      path_entries=self.path_entries(),
      exe_filename='as',
      library_dirs=[])

  def linker(self):
    return Linker(
      path_entries=self.path_entries(),
      exe_filename='ld',
      library_dirs=[],
      linking_library_dirs=[],
      extra_args=[])


@rule(Assembler, [Select(Binutils)])
def get_as(binutils):
  return binutils.assembler()


@rule(Linker, [Select(Binutils)])
def get_ld(binutils):
  return binutils.linker()


def create_binutils_rules():
  return [
    get_as,
    get_ld,
  ]
