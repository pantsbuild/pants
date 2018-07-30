# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

main_file = 'main.py'

python_dist(
  sources=rglobs('*.py', exclude=[main_file]),
  setup_requires=[
    # FIXME: this currently fails because setup_requires doesn't fetch transitive deps!
    'testprojects/pants-plugins/3rdparty/python/pants',
  ],
)

python_binary(
  name='bin',
  sources=[main_file],
  dependencies=[':pants_setup_requires'],
)
