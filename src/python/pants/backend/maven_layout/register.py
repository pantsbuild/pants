# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.backend.maven_layout.maven_layout import maven_layout
from pants.base.build_file_aliases import BuildFileAliases


def register_goals():
  pass


def register_commands():
  pass


def build_file_aliases():
  return BuildFileAliases.create(macros={'maven_layout': maven_layout})
