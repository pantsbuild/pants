# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from setuptools import setup, find_packages
from distutils.core import Extension


c_module = Extension(str('super_greet'), sources=[str('super_greet.c')])

# This setup.py is supposed to conflict with the flask 0.12.1 requirement 
# pulled in from the requirement library in the BUILD file. 
setup(
  name='flask',
  version='0.12.2',
  ext_modules=[c_module],
  packages=find_packages(),
)
