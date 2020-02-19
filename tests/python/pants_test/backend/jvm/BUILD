# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name = 'jar_dependency_utils',
  sources = ['test_jar_dependency_utils.py'],
  dependencies = [
    'src/python/pants/java/jar',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name='integration',
  sources=['*_integration.py'],
  dependencies=[
    'src/python/pants/testutil:int-test',
    'examples/tests/java/org/pantsbuild/example:hello_directory',
  ],
  tags={'integration', 'partially_type_checked'},
  timeout=300
)
