# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_binary(
  name = 'reversion',
  sources = ['reversion.py'],
  dependencies = [
    '3rdparty/python:setuptools',  # Needed because we suck in pants/__init__.py, which invokes it.
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
  ],
)
