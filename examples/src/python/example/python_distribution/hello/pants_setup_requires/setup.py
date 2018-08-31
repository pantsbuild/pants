# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from setuptools import setup, find_packages

from pants.version import VERSION as pants_version

setup(
  name='hello_again',
  version=pants_version,
  packages=find_packages(),
)
