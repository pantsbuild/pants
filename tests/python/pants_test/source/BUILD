# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name = 'source_root',
  sources = ['test_source_root.py'],
  dependencies = [
    'src/python/pants/source',
    'tests/python/pants_test/subsystem:subsystem_utils',
    'tests/python/pants_test:base_test',
  ],
)

python_tests(
  name = 'payload_fields',
  sources = ['test_payload_fields.py'],
  dependencies = [
    'src/python/pants/source',
    'tests/python/pants_test:base_test',
  ],
)

python_tests(
  name = 'wrapped_globs',
  sources = ['test_wrapped_globs.py'],
  dependencies = [
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/build_graph',
    'src/python/pants/source',
    'tests/python/pants_test:base_test',
  ],
)
