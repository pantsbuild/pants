# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import subprocess

from pants.base.build_environment import get_buildroot
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class WireIntegrationTest(PantsRunIntegrationTest):

  def test_good(self):
    # wire example should compile without warnings with correct wire files.

    # force a compile to happen, we count on compile output in this test
    self.assert_success(self.run_pants(['clean-all']))

    pants_run = self.run_pants(['compile',
                                'examples/src/java/org/pantsbuild/example/wire/temperature'])
    self.assert_success(pants_run)

    expected_outputs = [
      'Compiling proto source file',
      'Created output directory',
      'Writing generated code',
      '/gen/wire/org/pantsbuild/example/temperature/Temperature.java',
    ]
    for expected_output in expected_outputs:
      self.assertIn(expected_output, pants_run.stdout_data)

  def test_bundle_wire_normal(self):
    pants_run = self.run_pants(['bundle',
                                '--deployjar',
                                'examples/src/java/org/pantsbuild/example/wire/temperature'])
    self.assert_success(pants_run)
    out_path = os.path.join(get_buildroot(), 'dist', 'wire-temperature-example-bundle')

    java_run = subprocess.Popen(['java', '-cp', 'wire-temperature-example.jar',
                                 'org.pantsbuild.example.wire.temperature.WireTemperatureExample'],
                                stdout=subprocess.PIPE,
                                cwd=out_path)
    java_retcode = java_run.wait()
    java_out = java_run.stdout.read()
    self.assertEquals(java_retcode, 0)
    self.assertIn('19 degrees celsius', java_out)

  def test_bundle_wire_dependent_targets(self):
    pants_run = self.run_pants(['bundle',
                                '--deployjar',
                                'examples/src/java/org/pantsbuild/example/wire/element'])
    self.assert_success(pants_run)
    out_path = os.path.join(get_buildroot(), 'dist', 'wire-element-example-bundle')

    java_run = subprocess.Popen(['java', '-cp', 'wire-element-example.jar',
                                 'org.pantsbuild.example.wire.element.WireElementExample'],
                                stdout=subprocess.PIPE,
                                cwd=out_path)
    java_retcode = java_run.wait()
    java_out = java_run.stdout.read()
    self.assertEquals(java_retcode, 0)
    self.assertIn('Element{symbol=Hg, name=Mercury, atomic_number=80, '
                  'melting_point=Temperature{unit=celsius, number=-39}, '
                  'boiling_point=Temperature{unit=celsius, number=357}}', java_out)
