# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from setuptools import setup, find_packages
from distutils.core import Extension


c_module = Extension('c_greet', sources=['c_greet.c'])
cpp_module = Extension('cpp_greet'), sources=['cpp_greet.cpp'])

setup(
  name='fasthello_test',
  version='1.0.0',
  ext_modules=[c_module, cpp_module],
  packages=find_packages(),
  install_requires=['pycountry==17.1.2']
)
