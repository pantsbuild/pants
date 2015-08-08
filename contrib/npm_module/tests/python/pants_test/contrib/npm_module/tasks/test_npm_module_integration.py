# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.util.contextutil import open_zip, temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class NpmModuleIntegrationTest(PantsRunIntegrationTest):
  def test_resource_preprocessor(self):
    # TODO fix in PantsRunIntegrationTest to yield workdir
    with temporary_dir(root_dir=self.workdir_root()) as workdir:
      command = ['bundle', '--archive=zip',
                 'contrib/npm_module/examples/src/java/org/pantsbuild/example/npm_module:main']
      self.run_pants_with_workdir(command, workdir)
      with open_zip('dist/npm_module-example-bundle/npm_module-example.jar') as jar:
        self.assertIn('contrib/npm_module/examples/src/resources/example_less.rtl.css',
                      jar.namelist())
        self.assertIn('min/main.js', jar.namelist())
