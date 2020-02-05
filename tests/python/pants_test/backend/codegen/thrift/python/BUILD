# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  dependencies=[
    '3rdparty/python:pex',
    'src/python/pants/backend/codegen/thrift/lib',
    'src/python/pants/backend/codegen/thrift/python',
    'src/python/pants/backend/python:interpreter_cache',
    'src/python/pants/backend/python/targets',
    'src/python/pants/base:build_environment',
    'src/python/pants/python',
    'src/python/pants/util:contextutil',
    'src/python/pants/testutil/subsystem',
    'src/python/pants/testutil:task_test_base',
  ],
  tags = {"partially_type_checked"},
)
