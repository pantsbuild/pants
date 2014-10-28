# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_test_suite(
  name = 'tasks',
  dependencies = [
    ':protobuf_parse',
    ':wire_gen',
  ],
)

python_tests(
  name = 'protobuf_parse',
  sources = ['test_protobuf_parse.py'],
  dependencies = [
    'src/python/pants/backend/codegen/tasks:protobuf_parse',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test/tasks:base',
  ],
)

python_tests(
  name = 'wire_gen',
  sources = ['test_wire_gen.py'],
  dependencies = [
    'src/python/pants/backend/codegen/tasks:wire_gen',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test/tasks:base',
  ],
)
