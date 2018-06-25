# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from setuptools import setup, find_packages
from distutils.core import Extension


c_module = Extension(str('c_greet'), sources=[str('c_greet.c')])
cpp_module = Extension(str('cpp_greet'), sources=[str('cpp_greet.cpp')])

public_version = '1.0.0'
local_version = os.getenv('_SETUP_PY_LOCAL_VERSION')
version = '{}+{}'.format(public_version, local_version) if local_version else public_version

setup(
  name='fasthello_test',
  version=version,
  ext_modules=[c_module, cpp_module],
  packages=find_packages(),
  install_requires=['pycountry==17.1.2']
)
