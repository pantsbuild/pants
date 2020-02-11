# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


python_tests(
  name = 'integration',
  sources = ['*_integration.py'],
  dependencies=[
    'src/python/pants/testutil:int-test',
    'examples/src/java/org/pantsbuild/example:hello_directory',
  ],
  tags={'integration', 'partially_type_checked'},
  timeout=240,
)
