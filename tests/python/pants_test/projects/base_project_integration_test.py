# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class ProjectIntegrationTest(PantsRunIntegrationTest):
  """
  :API: public
  """

  def pants_test(self, command):
    """
    :API: public
    """
    return self.run_pants(['test'] + command)
