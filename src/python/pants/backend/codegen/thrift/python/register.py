# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.codegen.thrift.python.apache_thrift_py_gen import ApacheThriftPyGen
from pants.backend.codegen.thrift.python.python_thrift_library import PythonThriftLibrary
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.goal.task_registrar import TaskRegistrar as task


def build_file_aliases():
  return BuildFileAliases(
    targets={
      'python_thrift_library': PythonThriftLibrary,
      }
    )


def register_goals():
  task(name='thrift-py', action=ApacheThriftPyGen).install('gen')
