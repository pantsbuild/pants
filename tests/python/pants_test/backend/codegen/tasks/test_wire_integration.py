# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re
import subprocess

from pants.base.build_environment import get_buildroot
from pants.util.contextutil import open_zip
from pants_test.pants_run_integration_test import PantsRunIntegrationTest
from pants_test.testutils.file_test_util import exact_files


class WireIntegrationTest(PantsRunIntegrationTest):

  def test_good(self):
    # wire example should compile without warnings with correct wire files.

    # force a compile to happen, we count on compile output in this test
    self.assert_success(self.run_pants(['clean-all']))

    with self.temporary_workdir() as workdir:
      cmd = ['compile', 'examples/src/java/org/pantsbuild/example/wire/temperatureservice']
      pants_run = self.run_pants_with_workdir(cmd, workdir)
      self.assert_success(pants_run)

      pattern = 'gen/wire/[^/]*/[^/]*/[^/]*/org/pantsbuild/example/temperature/Temperature.java'
      files = exact_files(workdir)
      self.assertTrue(any(re.match(pattern, f) is not None for f in files),
                      'Expected pattern: {} in {}'.format(pattern, files))

  def test_bundle_wire_normal(self):
    with self.pants_results(['bundle.jvm',
                         '--deployjar',
                         'examples/src/java/org/pantsbuild/example/wire/temperatureservice']
                        ) as pants_run:
      self.assert_success(pants_run)
      out_path = os.path.join(get_buildroot(), 'dist',
                              ('examples.src.java.org.pantsbuild.example.wire.temperatureservice.'
                              'temperatureservice-bundle'))

      args = ['java', '-cp', 'wire-temperature-example.jar',
              'org.pantsbuild.example.wire.temperatureservice.WireTemperatureExample']
      java_run = subprocess.Popen(args, stdout=subprocess.PIPE, cwd=out_path)
      java_retcode = java_run.wait()
      java_out = java_run.stdout.read()
      self.assertEquals(java_retcode, 0)
      self.assertIn('19 degrees celsius', java_out)

  def test_bundle_wire_dependent_targets(self):
    with self.pants_results(['bundle.jvm',
                             '--deployjar',
                             'examples/src/java/org/pantsbuild/example/wire/element']
                            ) as pants_run:
      self.assert_success(pants_run)
      out_path = os.path.join(get_buildroot(), 'dist',
                              'examples.src.java.org.pantsbuild.example.wire.element.element-bundle')

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
      self.assertIn('Compound{name=Water, primary_element=Element{symbol=O, name=Oxygen, '
                    'atomic_number=8}, secondary_element=Element{symbol=H, name=Hydrogen, '
                    'atomic_number=1}}', java_out)

  def test_compile_wire_roots(self):
    pants_run = self.run_pants(['bundle.jvm', '--deployjar',
                                'examples/src/java/org/pantsbuild/example/wire/roots'])
    self.assert_success(pants_run)
    out_path = os.path.join(get_buildroot(), 'dist', 'wire-roots-example.jar')
    with open_zip(out_path) as zipfile:
      jar_entries = zipfile.namelist()

    def is_relevant(entry):
      return (entry.startswith('org/pantsbuild/example/roots/') and entry.endswith('.class')
              and '$' not in entry)

    expected_classes = {
      'org/pantsbuild/example/roots/Bar.class',
      'org/pantsbuild/example/roots/Foobar.class',
      'org/pantsbuild/example/roots/Fooboo.class',
    }
    received_classes = {entry for entry in jar_entries if is_relevant(entry)}
    self.assertEqual(expected_classes, received_classes)
