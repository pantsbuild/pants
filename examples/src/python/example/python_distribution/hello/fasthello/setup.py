# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import sys

from setuptools import setup, find_packages
from distutils.core import Extension

PY3 = sys.version_info[0] == 3

if PY3:
  c_module = Extension('c_greet', sources=['c_greet.c'])
  cpp_module = Extension('cpp_greet', sources=['cpp_greet.cpp'])
else:
  c_module = Extension(b'c_greet', sources=[b'c_greet.c'])
  cpp_module = Extension(b'cpp_greet', sources=[b'cpp_greet.cpp'])

setup(
  name='fasthello',
  version='1.0.0',
  ext_modules=[c_module, cpp_module],
  packages=find_packages(),
)
