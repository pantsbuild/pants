# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.python.targets.python_tests import PythonTests

from test_pants_plugin.subsystems.python_test_infra import PythonTestInfra


class PantsInfraTests(object):

  def __init__(self, parse_context):
    self._parse_context = parse_context
    self._python_test_infra = PythonTestInfra.global_instance()

  def __call__(self, dependencies=[], **kwargs):
    dependencies.extend(self._python_test_infra.dependent_target_addrs())
    self._parse_context.create_object(
      PythonTests.alias(), dependencies=dependencies, **kwargs)
