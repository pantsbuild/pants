# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from setuptools import find_packages, setup

setup(
    name="tensorflow_custom_op",
    version="0.0.1",
    packages=find_packages(),
    data_files=[("", ["libtensorflow-zero-out-operator.so"])],
)
