# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.native.subsystems.native_toolchain import NativeToolchain
from pants.engine.rules import RootRule, SingletonRule
from pants.util.objects import datatype
from pants.util.osutil import get_normalized_os_name


class Platform(datatype(['normalized_os_name'])):

  def __new__(cls):
    return super(Platform, cls).__new__(cls, get_normalized_os_name())


def rules():
  return [
    RootRule(NativeToolchain),
    SingletonRule(Platform, Platform()),
  ]
