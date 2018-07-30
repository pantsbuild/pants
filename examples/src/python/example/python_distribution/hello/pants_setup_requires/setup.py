# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
from setuptools import setup, find_packages

from pants.version import VERSION as pants_version

setup(
  name='hello',
  # FIXME: test the wheel version in a unit test!
  version=pants_version,
  packages=find_packages(),
)
