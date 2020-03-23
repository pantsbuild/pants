# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


python_tests(
  name='integration',
  dependencies=[
    'src/python/pants/base:build_environment',
    'src/python/pants/bin',
    'src/python/pants/option',
    'src/python/pants/testutil:int-test',
    'testprojects:pants_plugins_directory',
    'testprojects/src/python:nested_runs_directory',
  ],
  tags = {'integration', 'partially_type_checked'},
)
