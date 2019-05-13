# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  dependencies=[
    '3rdparty/python:future',
    '3rdparty/python:pex',
    '3rdparty/python:six',
    'src/python/pants/backend/codegen/thrift/lib',
    'src/python/pants/backend/codegen/thrift/python',
    'src/python/pants/backend/python:interpreter_cache',
    'src/python/pants/backend/python/subsystems',
    'src/python/pants/backend/python/targets:python',
    'src/python/pants/base:build_environment',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:process_handler',
    'tests/python/pants_test/subsystem:subsystem_utils',
    'tests/python/pants_test:console_rule_test_base',
    'tests/python/pants_test:task_test_base',
  ]
)
