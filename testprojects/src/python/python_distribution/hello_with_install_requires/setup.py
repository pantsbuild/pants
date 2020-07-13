# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from setuptools import find_packages, setup

setup(
    name="hello_with_install_requires",
    version="1.0.0",
    packages=find_packages(),
    install_requires=["pycountry==17.1.2"],
)
