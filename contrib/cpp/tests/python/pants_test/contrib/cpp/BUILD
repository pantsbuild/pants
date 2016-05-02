# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name='cpp_integration',
  sources=[
    'test_cpp_integration.py'
  ],
  dependencies = [
    'contrib/cpp/src/python/pants/contrib/cpp/toolchain',
    'tests/python/pants_test:int-test',
  ],
  tags={'integration'},
)

python_tests(
  name='cpp_toolchain',
  sources=[
    'test_cpp_toolchain.py',
  ],
  dependencies = [
    'contrib/cpp/src/python/pants/contrib/cpp/toolchain',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
  ],
)
