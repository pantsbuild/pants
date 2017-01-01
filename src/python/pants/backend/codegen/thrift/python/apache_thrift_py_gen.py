# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.codegen.thrift.lib.apache_thrift_gen_base import ApacheThriftGenBase
from pants.backend.codegen.thrift.python.python_thrift_library import PythonThriftLibrary
from pants.backend.python.targets.python_library import PythonLibrary


class ApacheThriftPyGen(ApacheThriftGenBase):
  thrift_library_target_type = PythonThriftLibrary
  thrift_generator = 'py'
  default_gen_options_map = {
    'new_style': None
  }

  def synthetic_target_type(self, target):
    return PythonLibrary

  def ignore_dup(self, tgt1, tgt2, rel_src):
    # Thrift generates all the intermediate __init__.py files, and they shouldn't
    # count as dups.
    return os.path.basename(rel_src) == '__init__.py'
