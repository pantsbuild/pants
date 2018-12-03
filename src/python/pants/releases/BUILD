# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_binary(
  name = 'reversion',
  source = 'reversion.py',
  dependencies = [
    '3rdparty/python:future',
    'src/python/pants/util:contextutil',
  ],
)

# Note that packages.py is not part of a target, it should be run with pex.
# Its dependencies and such can be found in build-support/bin/release.sh.
