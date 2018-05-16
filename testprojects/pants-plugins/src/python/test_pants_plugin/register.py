# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from test_pants_plugin.pants_infra_tests import PantsInfraTests
from test_pants_plugin.subsystems.pants_test_infra import PantsTestInfra

from pants.build_graph.build_file_aliases import BuildFileAliases


def build_file_aliases():
  return BuildFileAliases(
    context_aware_object_factories={
      'pants_infra_tests': PantsInfraTests,
    }
  )

def global_subsystems():
  return (PantsTestInfra,)
