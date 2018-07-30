# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_dist(
  sources=globs('*.py'),
  setup_requires=[
    # FIXME: this currently fails because setup_requires doesn't fetch transitive deps!
    'testprojects/pants-plugins/3rdparty/python/pants',
  ],
)
