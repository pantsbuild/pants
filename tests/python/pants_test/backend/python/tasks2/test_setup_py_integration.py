# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import re
import tarfile

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class SetupPyIntegrationTest(PantsRunIntegrationTest):

  def assert_sdist(self, pants_run, key, files):
    sdist_path = 'dist/{}-0.0.1.tar.gz'.format(key)
    self.assertTrue(re.search(r'Writing .*/{}'.format(sdist_path), pants_run.stdout_data))

    src_entries = ['src/{}'.format(f) for f in files]

    egg_info_entries = [
      'src/{}.egg-info/{}'.format(key.replace('-', '_'), relpath) for relpath in [
        '',
        'dependency_links.txt',
        'PKG-INFO',
        'requires.txt',
        'SOURCES.txt',
        'namespace_packages.txt',
        'top_level.txt',
      ]
    ]

    expected_entries = [
      '{}-0.0.1/{}'.format(key, relpath) for relpath in [
        '',
        'MANIFEST.in',
        'PKG-INFO',
        'setup.cfg',
        'setup.py',
        'src/',
      ] + src_entries + egg_info_entries
    ]

    with tarfile.open(sdist_path, 'r') as sdist:
      infos = sdist.getmembers()
      entries = [(info.name.rstrip('/') + '/' if info.isdir() else info.name) for info in infos]
      self.assertEquals(sorted(expected_entries), sorted(entries),
                        '\nExpected entries:\n{}\n\nActual entries:\n{}'.format(
                          '\n'.join(sorted(expected_entries)),
                          '\n'.join(sorted(entries))))

  def test_setup_py_with_codegen_simple(self):
    self.maxDiff = None

    command = ['setup-py',
               'examples/src/thrift/org/pantsbuild/example/distance:distance-python']
    pants_run = self.run_pants(command=command)
    self.assert_success(pants_run)

    self.assert_sdist(pants_run,
                      'pantsbuild.pants.distance-thrift-python',
                      ['org/',
                       'org/__init__.py',
                       'org/pantsbuild/',
                       'org/pantsbuild/__init__.py',
                       'org/pantsbuild/example/',
                       'org/pantsbuild/example/__init__.py',
                       'org/pantsbuild/example/distance/',
                       'org/pantsbuild/example/distance/__init__.py',
                       'org/pantsbuild/example/distance/constants.py',
                       'org/pantsbuild/example/distance/ttypes.py'])

  def test_setup_py_with_codegen_exported_deps(self):
    self.maxDiff = None

    command = ['setup-py',
               '--recursive',
               'examples/src/thrift/org/pantsbuild/example/precipitation:precipitation-python']
    pants_run = self.run_pants(command=command)
    self.assert_success(pants_run)

    self.assert_sdist(pants_run,
                      'pantsbuild.pants.precipitation-thrift-python',
                      ['org/',
                       'org/__init__.py',
                       'org/pantsbuild/',
                       'org/pantsbuild/__init__.py',
                       'org/pantsbuild/example/',
                       'org/pantsbuild/example/__init__.py',
                       'org/pantsbuild/example/precipitation/',
                       'org/pantsbuild/example/precipitation/__init__.py',
                       'org/pantsbuild/example/precipitation/constants.py',
                       'org/pantsbuild/example/precipitation/ttypes.py'])

    self.assert_sdist(pants_run,
                      'pantsbuild.pants.distance-thrift-python',
                      ['org/',
                       'org/__init__.py',
                       'org/pantsbuild/',
                       'org/pantsbuild/__init__.py',
                       'org/pantsbuild/example/',
                       'org/pantsbuild/example/__init__.py',
                       'org/pantsbuild/example/distance/',
                       'org/pantsbuild/example/distance/__init__.py',
                       'org/pantsbuild/example/distance/constants.py',
                       'org/pantsbuild/example/distance/ttypes.py'])

  def test_setup_py_with_codegen_unexported_deps(self):
    self.maxDiff = None

    command = [
      'setup-py',
      'examples/src/thrift/org/pantsbuild/example/precipitation:monolithic-precipitation-python'
    ]
    pants_run = self.run_pants(command=command)
    self.assert_success(pants_run)

    self.assert_sdist(pants_run,
                      'pantsbuild.pants.monolithic-precipitation-thrift-python',
                      ['org/',
                       'org/__init__.py',
                       'org/pantsbuild/',
                       'org/pantsbuild/__init__.py',
                       'org/pantsbuild/example/',
                       'org/pantsbuild/example/__init__.py',
                       'org/pantsbuild/example/distance/',
                       'org/pantsbuild/example/distance/__init__.py',
                       'org/pantsbuild/example/distance/constants.py',
                       'org/pantsbuild/example/distance/ttypes.py',
                       'org/pantsbuild/example/precipitation/',
                       'org/pantsbuild/example/precipitation/__init__.py',
                       'org/pantsbuild/example/precipitation/constants.py',
                       'org/pantsbuild/example/precipitation/ttypes.py'])
