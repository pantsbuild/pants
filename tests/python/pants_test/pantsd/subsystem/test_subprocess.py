# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from contextlib import contextmanager

from pants.pantsd.subsystem.subprocess import Subprocess
from pants_test.base_test import BaseTest
from pants_test.subsystem.subsystem_util import subsystem_instance


class SubprocessTest(BaseTest):
  @contextmanager
  def subprocess(self):
    with subsystem_instance(Subprocess.Factory) as factory:
      yield factory.create()

  def test_get_subprocess_dir(self):
    with self.subprocess() as subprocess:
      self.assertTrue(subprocess.get_subprocess_dir().endswith('/.pids'))
