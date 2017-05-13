# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class JarDependencyIntegrationTest(PantsRunIntegrationTest):

  def test_resolve_relative(self):
    pants_run = self.run_pants(['resolve', 'testprojects/3rdparty/org/pantsbuild/testprojects'])
    self.assert_success(pants_run)
