# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from distutils.core import Extension
from setuptools import find_packages

# FIXME: do an integration test showing that each of these works (can be imported and run)!
try:
  from pants.backend.python.distutils_extensions import pants_setup as setup
except ImportError:
  from setuptools import setup


c_module = Extension(b'hello', sources=[b'hello.c'])

setup(
  name='distutils_extensions',
  version='0.0.1',
  ext_modules=[c_module],
  packages=find_packages(),
)
