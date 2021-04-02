# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  sources=["*.py", "!pants_loader.py"],
)

python_library(
  name="pants_loader",
  sources=["pants_loader.py"],
)

# This binary's entry_point is used by the pantsbuild.pants sdist to setup a binary for
# pip installers, ie: it is why this works to get `pants` on your PATH:
# $ pip install pantsbuild.pants
# $ pants
pex_binary(
  name='pants',
  entry_point='pants.bin.pants_loader:main',
  dependencies=[
    ':pants_loader',
  ],
  # We depend on twitter.common libraries that trigger pex warnings for not properly declaring their
  # dependency on setuptools (for namespace package support).
  emit_warnings=False,
)

python_tests(name="tests")
