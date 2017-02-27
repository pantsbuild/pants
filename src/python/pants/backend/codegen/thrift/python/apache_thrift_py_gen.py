# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.codegen.thrift.lib.apache_thrift_gen_base import ApacheThriftGenBase
from pants.backend.codegen.thrift.python.python_thrift_library import PythonThriftLibrary
from pants.backend.python.targets.python_library import PythonLibrary
from pants.util.dirutil import safe_delete


class ApacheThriftPyGen(ApacheThriftGenBase):
  """Generate Python source files from thrift IDL files."""
  gentarget_type = PythonThriftLibrary
  thrift_generator = 'py'
  default_gen_options_map = {
    'new_style': None
  }

  def synthetic_target_type(self, target):
    return PythonLibrary

  def execute_codegen(self, target, target_workdir):
    super(ApacheThriftPyGen, self).execute_codegen(target, target_workdir)
    # Thrift puts an __init__.py file at the root, and we don't want one there
    # (it's not needed, and it confuses some import mechanisms).
    safe_delete(os.path.join(target_workdir, '__init__.py'))

  def ignore_dup(self, tgt1, tgt2, rel_src):
    # Thrift generates all the intermediate __init__.py files, and they shouldn't
    # count as dups.
    return os.path.basename(rel_src) == '__init__.py'
