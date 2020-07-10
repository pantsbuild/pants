# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  sources=["*.py", "!pants_exe.py", "!pants_loader.py"],
)

python_library(
  name="pants_exe",
  sources=["pants_exe.py"],
)

python_library(
  name="pants_loader",
  sources=["pants_loader.py"],
  dependencies=[
    ":pants_exe",  # NB: This is not inferred.
  ],
)

# This binary's entry_point is used by the pantsbuild.pants sdist to setup a binary for
# pip installers, ie: it is why this works to get `pants` on your PATH:
# $ pip install pantsbuild.pants
# $ pants
python_binary(
  name='pants',
  entry_point='pants.bin.pants_loader:main',
  dependencies=[
    ':pants_loader',
  ],
  # We depend on twitter.common libraries that trigger pex warnings for not properly declaring their
  # dependency on setuptools (for namespace package support).
  emit_warnings=False,
)

# This binary is for internal use only. It adds deps on internal_backends and build-support config
# files, both of which are not meant for publishing in the `pantsbuild.pants` sdist.
python_binary(
  name='pants_local_binary',
  entry_point='pants.bin.pants_loader:main',
  dependencies=[
    ':pants_loader',
    '//:build_root',
    '//:pants_toml',
    '//:3rdparty_directory',
    '//:isort_cfg',
    '//:pyproject',
    'build-support/flake8',
    'build-support/mypy',
    'build-support/regexes',
    'pants-plugins/src/python/internal_backend:plugins',
  ],
  # We depend on twitter.common libraries that trigger pex warnings for not properly declaring their
  # dependency on setuptools (for namespace package support).
  emit_warnings=False,
  # To allow for loading `native_engine.so` when built as a pex, we set zip_safe=False.
  zip_safe=False,
)
