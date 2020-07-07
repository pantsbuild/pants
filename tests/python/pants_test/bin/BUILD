# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name='integration',
  dependencies=[
    'testprojects:pants_plugins_directory',
    'testprojects/src/python:nested_runs_directory',
  ],
  tags = ['integration'],
  timeout = 120,
)
