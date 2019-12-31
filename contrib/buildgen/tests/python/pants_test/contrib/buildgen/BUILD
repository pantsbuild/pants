# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name = 'build_file_manipulator',
  sources = ['test_build_file_manipulator.py'],
  dependencies = [
    'contrib/buildgen/src/python/pants/contrib/buildgen:build_file_manipulator',
    'src/python/pants/base:build_file',
    'src/python/pants/base:project_tree',
    'src/python/pants/build_graph',
    'src/python/pants/testutil:test_base',
  ],
  tags = {'partially_type_checked'},
)
