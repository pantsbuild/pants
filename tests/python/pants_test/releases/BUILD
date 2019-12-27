# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  sources = ['test_reversion.py'],
  dependencies = [
    '3rdparty/python:pex',
    '3rdparty/python:requests',
    'src/python/pants/testutil:int-test',
    'src/python/pants:reversion_file_with_dependencies',
  ],
  tags = {'integration', 'partially_type_checked'},
)
