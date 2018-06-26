# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
from setuptools import setup, find_packages

# We require pycountry with setup_requires argument to this setup script's
# corresponding python_dist.
import pycountry

# This is for testing purposes so we can assert that setup_requires is functioning
# correctly (because Pants swallows print statements).
if os.getenv('PANTS_TEST_SETUP_REQUIRES', ''):
  output = [str(pycountry)]
  output.extend(os.listdir(os.getenv('PYTHONPATH', '')))
  raise Exception(str(output))

public_version = '1.0.0'
local_version = os.getenv('_SETUP_PY_LOCAL_VERSION')
version = '{}+{}'.format(public_version, local_version) if local_version else public_version

setup(
  name='hello',
  version=version,
  packages=find_packages(),
)
