# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from textwrap import dedent

from pants.util.dirutil import safe_open
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class GoTestIntegrationTest(PantsRunIntegrationTest):
  def test_go_test_simple(self):
    args = ['test',
            'contrib/go/examples/src/go/libA']
    pants_run = self.run_pants(args)
    self.assert_success(pants_run)

  def test_go_test_unstyle(self):
    with self.temporary_sourcedir() as srcdir:
      lib_unstyle_relpath = 'src/go/libUnstyle'
      lib_unstyle_dir = os.path.join(srcdir, lib_unstyle_relpath)
      with safe_open(os.path.join(lib_unstyle_dir, 'unstyle.go'), 'w') as fp:
        # NB: Go format violating indents below.
        fp.write(dedent("""
            package libUnstyle

            func Speak() {
              println("Hello from libUnstyle!")
              println("Bye from libUnstyle!")
            }

            func Add(a int, b int) int {
            return a + b
            }
            """).strip())
      with safe_open(os.path.join(lib_unstyle_dir, 'BUILD'), 'w') as fp:
        fp.write('go_library()')

      args = ['compile', 'lint', lib_unstyle_dir]
      pants_run = self.run_pants(args)
      self.assert_failure(pants_run)

      args = ['compile', 'lint', '--lint-go-skip', lib_unstyle_dir]
      pants_run = self.run_pants(args)
      self.assert_success(pants_run)
