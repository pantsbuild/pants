# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import re

import pex.resolver
from twitter.common.collections import OrderedDict

from pants.backend.python.python_requirement import PythonRequirement
from pants.backend.python.targets.python_distribution import PythonDistribution
from pants.backend.python.targets.python_library import PythonLibrary
from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants_test.backend.python.tasks.util.build_local_dists_test_base import \
  BuildLocalPythonDistributionsTestBase


class TestBuildLocalPythonDistributions(BuildLocalPythonDistributionsTestBase):

  dist_specs = OrderedDict([

    ('src/python/dist:universal_dist', {
      'key': 'universal',
      'target_type': PythonDistribution,
      'sources': ['__init__.py', 'setup.py'],
      'filemap': {
        '__init__.py': '',
        'setup.py': """\
from setuptools import find_packages, setup
setup(
  name='universal_dist',
  version='0.0.0',
  packages=find_packages()
)
        """,
      },
    }),

    ('3rdparty/python:pycountry', {
      'key': 'pycountry',
      'target_type': PythonRequirementLibrary,
      'requirements': [
        PythonRequirement('pycountry==18.5.20'),
      ],
    }),

    ('src/python/setup_requires:setup_requires', {
      'key': 'setup_requires',
      'target_type': PythonDistribution,
      'setup_requires': [
        '3rdparty/python:pycountry',
      ],
      'sources': ['__init__.py', 'setup.py'],
      'filemap': {
        '__init__.py': '',
        'setup.py': """\
from setuptools import find_packages, setup
import pycountry

us_country_string = pycountry.countries.get(alpha_2='US').name.replace(' ', '_').lower()

setup(
  name='setup_requires_dist_{}'.format(us_country_string),
  version='0.0.0',
  packages=find_packages(),
)
        """,
      },
    }),

    ('src/python/install_requires:install_requires', {
      'key': 'install_requires',
      'target_type': PythonDistribution,
      'sources': ['__init__.py', 'setup.py'],
      'filemap': {
        '__init__.py': '',
        'setup.py': """\
from setuptools import setup

setup(
  name='install_requires_dist',
  version='0.0.0',
  install_requires=['pycountry==17.1.2'],
)
        """,
      },
    }),

    ('src/python/install_requires:conflict', {
      'key': 'install_requires_conflict',
      'target_type': PythonLibrary,
      'dependencies': [
        '3rdparty/python:pycountry',
        'src/python/install_requires:install_requires',
      ],
    }),
  ])

  def test_create_distribution(self):
    universal_dist = self.target_dict['universal']
    self._assert_dist_and_wheel_identity(
      'universal_dist', '0.0.0', self.ExpectedPlatformType.universal, universal_dist)

  def test_python_dist_setup_requires(self):
    setup_requires_dist = self.target_dict['setup_requires']
    self._assert_dist_and_wheel_identity(
      'setup_requires_dist_united_states', '0.0.0', self.ExpectedPlatformType.universal,
      setup_requires_dist, extra_targets=[self.target_dict['pycountry']])

  def test_install_requires(self):
    install_requires_dist = self.target_dict['install_requires']
    self._assert_dist_and_wheel_identity(
      'install_requires_dist', '0.0.0', self.ExpectedPlatformType.universal,
      install_requires_dist)

  def test_install_requires_conflict(self):
    install_requires_dist = self.target_dict['install_requires']
    pycountry_req_lib = self.target_dict['pycountry']
    conflicting_lib = self.target_dict['install_requires_conflict']

    with self.assertRaisesRegexp(
        pex.resolver.Unsatisfiable,
        re.escape('Could not satisfy all requirements for pycountry==18.5.20:')):
      self._create_distribution_synthetic_target(
        install_requires_dist,
        extra_targets=[pycountry_req_lib, conflicting_lib])
