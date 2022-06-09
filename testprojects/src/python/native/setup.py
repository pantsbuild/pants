# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from colors import red
from setuptools import Extension, setup

native_impl = Extension("native.impl", sources=["impl.c"])

setup(
    name="native",
    version="2.3.4",
    packages=["native"],
    namespace_packages=["native"],
    package_dir={"native": "."},
    ext_modules=[native_impl],
    description=red("Proof that custom PEP-517 build-time requirements work"),
)
