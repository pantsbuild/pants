# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name = 'changed_target_integration',
  sources = ['test_changed_target_integration.py'],
  dependencies = [
    'src/python/pants/base:build_environment',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/testutil:int-test',
    'src/python/pants/testutil:git_util',
  ],
  tags = {'integration', 'partially_type_checked'},
  timeout=540,
)

