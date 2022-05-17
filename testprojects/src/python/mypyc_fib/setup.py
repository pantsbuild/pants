# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Note that we don't want to infer a dep on mypyc, as it's provided by the dist build system due
# to uses_mypyc=True in the BUILD file. We therefore also ignore typechecking in this file.

# type: ignore

from mypyc.build import mypycify  # pants: no-infer-dep
from setuptools import setup

setup(
    name="mypyc_fib",
    version="2.3.4",
    packages=["mypyc_fib"],
    ext_modules=mypycify(["mypyc_fib/__init__.py", "mypyc_fib/fib.py"]),
    description="Proof that mypyc compilation works",
)
