# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.base.build_environment import get_buildroot
from pants.base.build_file_aliases import BuildFileAliases


def read_contents_factory(parse_context):
  def read_contents(path, relative_to_buildroot=False):
    base_dir = get_buildroot() if relative_to_buildroot else parse_context.rel_path
    with open(os.path.join(base_dir, path)) as fp:
      return fp.read()
  return read_contents


def build_file_aliases():
  return BuildFileAliases.create(
    context_aware_object_factories={
      'read_contents': read_contents_factory
    }
  )
