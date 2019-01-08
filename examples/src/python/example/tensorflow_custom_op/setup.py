# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from setuptools import setup, find_packages

setup(
  name='tensorflow_custom_op',
  version='0.0.1',
  packages=find_packages(),
  data_files=[('', ['libtensorflow-zero-out-operator.so'])],
)
