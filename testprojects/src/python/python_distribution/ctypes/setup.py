# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from setuptools import setup, find_packages

public_version = '0.0.1'
local_version = os.getenv('_SETUP_PY_LOCAL_VERSION')
version = '{}+{}'.format(public_version, local_version) if local_version else public_version

setup(
  name='ctypes_test',
  version=version,
  packages=find_packages(),
  # Declare two files at the top-level directory (denoted by '').
  data_files=[('', ['libasdf-c.so', 'libasdf-cpp.so'])],
)
