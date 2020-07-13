# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from setuptools import find_packages, setup

setup(
    name="ctypes_test",
    version="0.0.1",
    packages=find_packages(),
    # Declare two files at the top-level directory (denoted by '').
    data_files=[("", ["libasdf-c_ctypes.so", "libasdf-cpp_ctypes.so"])],
)
