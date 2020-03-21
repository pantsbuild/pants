# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from collections import OrderedDict

from pants.backend.python.targets.python_distribution import PythonDistribution
from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.python.python_requirement import PythonRequirement
from pants_test.backend.python.tasks.util.build_local_dists_test_base import (
    BuildLocalPythonDistributionsTestBase,
)


class TestBuildLocalPythonDistributions(BuildLocalPythonDistributionsTestBase):

    dist_specs = OrderedDict(
        [
            (
                "src/python/dist:universal_dist",
                {
                    "key": "universal",
                    "target_type": PythonDistribution,
                    "sources": ["__init__.py", "setup.py"],
                    "filemap": {
                        "__init__.py": "",
                        "setup.py": """\
from setuptools import find_packages, setup
setup(
  name='universal_dist',
  version='0.0.0',
  packages=find_packages()
)
        """,
                    },
                },
            ),
            (
                "3rdparty/python:pycountry",
                {
                    "key": "pycountry",
                    "target_type": PythonRequirementLibrary,
                    "requirements": [PythonRequirement("pycountry==18.5.20")],
                },
            ),
            (
                "src/python/setup_requires:setup_requires",
                {
                    "key": "setup_requires",
                    "target_type": PythonDistribution,
                    "setup_requires": ["3rdparty/python:pycountry"],
                    "sources": ["__init__.py", "setup.py"],
                    "filemap": {
                        "__init__.py": "",
                        "setup.py": """\
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
                },
            ),
            (
                "src/python/install_requires:install_requires",
                {
                    "key": "install_requires",
                    "target_type": PythonDistribution,
                    "sources": ["__init__.py", "setup.py"],
                    "filemap": {
                        "__init__.py": "",
                        "setup.py": """\
from setuptools import setup

setup(
  name='install_requires_dist',
  version='0.0.0',
  install_requires=['pycountry==17.1.2'],
)
        """,
                    },
                },
            ),
        ]
    )

    def test_create_distribution(self):
        universal_dist = self.target_dict["universal"]
        self._assert_dist_and_wheel_identity(
            expected_name="universal_dist",
            expected_version="0.0.0",
            expected_platform=self.ExpectedPlatformType.any,
            dist_target=universal_dist,
        )

    def test_python_dist_setup_requires(self):
        setup_requires_dist = self.target_dict["setup_requires"]
        self._assert_dist_and_wheel_identity(
            expected_name="setup_requires_dist_united_states",
            expected_version="0.0.0",
            expected_platform=self.ExpectedPlatformType.any,
            dist_target=setup_requires_dist,
            extra_targets=[self.target_dict["pycountry"]],
        )

    def test_install_requires(self):
        install_requires_dist = self.target_dict["install_requires"]
        self._assert_dist_and_wheel_identity(
            expected_name="install_requires_dist",
            expected_version="0.0.0",
            expected_platform=self.ExpectedPlatformType.any,
            dist_target=install_requires_dist,
        )
