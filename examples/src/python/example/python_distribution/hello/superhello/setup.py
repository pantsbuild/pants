# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from distutils.core import setup, Extension

# A setup.py file is necessary to define your python_distribution
# In your setup.py file, define Extensions to include in ext_modules for your python package
c_module = Extension(str('super_greet'), sources=[str('c/super_greet.c')])

setup(name='superhello', version='1.0',
      description='Python Package with C Extension',
      ext_modules=[c_module])
