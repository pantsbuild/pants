# coding=utf-8
# Copyright YYYY Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)


from distutils.core import setup, Extension

# A setup.py file is necessary to define your python_distribution
# In your setup.py file, define an Extension to include in ext_modules for your python package
# is Extension doing any compilation?
greet_module = Extension('hello', sources=['cpp/greet.cpp'])

setup(name='superhello', version='1.0',
      description='Python Package with superhello C++ Extension',
      ext_modules=[greet_module])
