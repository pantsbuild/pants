# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_binary(
  name='test',
  source='test_binary.py',
  dependencies=[':test_library']
)

python_library(
  name='test_library',
  sources=['test_library.py']
)

python_library(
  name='test_library_direct_dependee',
  sources=[],
  dependencies=[':test_library']
)

python_library(
  name='test_library_transitive_dependee',
  sources=[],
  dependencies=[':test_library_direct_dependee']
)

python_library(
  name='test_library_transitive_dependee_2',
  sources=[],
  dependencies=[':test_library_transitive_dependee']
)

python_library(
  name='test_library_transitive_dependee_3',
  sources=[],
  dependencies=[':test_library_transitive_dependee']
)

python_library(
  name='test_library_transitive_dependee_4',
  sources=[],
  dependencies=[':test_library_transitive_dependee_3']
)
