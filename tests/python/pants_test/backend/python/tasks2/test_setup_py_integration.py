# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import re
import tarfile

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class SetupPyIntegrationTest(PantsRunIntegrationTest):

  def test_setup_py_with_codegen(self):
    self.maxDiff = None

    sdist_path = 'dist/pantsbuild.pants.distance-thrift-python-0.0.1.tar.gz'

    command = ['setup-py',
               'examples/src/thrift/org/pantsbuild/example/distance:distance-python']
    pants_run = self.run_pants(command=command)
    self.assert_success(pants_run)
    self.assertTrue(re.search(r'Writing .*/{}'.format(sdist_path), pants_run.stdout_data))
    with tarfile.open(sdist_path, 'r') as sdist:
      entries = sdist.getnames()
    print(entries)
    expected_prefix = 'pantsbuild.pants.distance-thrift-python-0.0.1'
    expected_entries = [
        expected_prefix + relpath for relpath in [
        '',
        '/MANIFEST.in',
        '/PKG-INFO',
        '/setup.cfg',
        '/setup.py',
        '/src',
        '/src/org',
        '/src/org/__init__.py',
        '/src/org/pantsbuild',
        '/src/org/pantsbuild/__init__.py',
        '/src/org/pantsbuild/example',
        '/src/org/pantsbuild/example/__init__.py',
        '/src/org/pantsbuild/example/distance',
        '/src/org/pantsbuild/example/distance/__init__.py',
        '/src/org/pantsbuild/example/distance/constants.py',
        '/src/org/pantsbuild/example/distance/ttypes.py',
        '/src/pantsbuild.pants.distance_thrift_python.egg-info',
        '/src/pantsbuild.pants.distance_thrift_python.egg-info/dependency_links.txt',
        '/src/pantsbuild.pants.distance_thrift_python.egg-info/PKG-INFO',
        '/src/pantsbuild.pants.distance_thrift_python.egg-info/requires.txt',
        '/src/pantsbuild.pants.distance_thrift_python.egg-info/SOURCES.txt',
        '/src/pantsbuild.pants.distance_thrift_python.egg-info/top_level.txt'
      ]
    ]
    self.assertEquals(
      sorted(expected_entries),
      sorted(entries)
    )
