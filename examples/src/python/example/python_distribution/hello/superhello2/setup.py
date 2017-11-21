# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        with_statement)

from setuptools import setup, find_packages
from distutils.core import Extension


c_module = Extension('super_greet', sources=['c/super_greet.c'])

setup(
    name='superhello2',
    version='1.0.0',
    ext_modules=[c_module],
    packages=find_packages(),
)
