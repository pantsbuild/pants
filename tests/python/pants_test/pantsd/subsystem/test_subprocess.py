# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.pantsd.subsystem.subprocess import Subprocess
from pants_test.base_test import BaseTest
from pants_test.subsystem.subsystem_util import global_subsystem_instance


class SubprocessTest(BaseTest):
  def subprocess(self):
    return global_subsystem_instance(Subprocess.Factory).create()

  def test_get_subprocess_dir(self):
    self.assertTrue(self.subprocess().get_subprocess_dir().endswith('/.pids'))
