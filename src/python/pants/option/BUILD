# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  dependencies=[
    '3rdparty/python:ansicolors',
    '3rdparty/python:dataclasses',
    '3rdparty/python:python-Levenshtein',
    '3rdparty/python:PyYAML',
    '3rdparty/python:setuptools',
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:deprecated',
    'src/python/pants/base:hash_utils',
    'src/python/pants/engine:selectors',
    'src/python/pants/util:collections',
    'src/python/pants/util:eval',
    'src/python/pants/util:meta',
    'src/python/pants/util:memo',
    'src/python/pants/util:strutil',
  ],
  tags = {'partially_type_checked'},
)

python_tests(
  name="tests",
  sources=globs('*_test.py', exclude=[globs('*_integration_test.py')]),
  dependencies=[
    ':option',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:hash_utils',
    'src/python/pants/base:deprecated',
    'src/python/pants/util:contextutil',
    'src/python/pants/testutil/option',
    'src/python/pants/testutil:test_base',
  ],
)

python_tests(
  name='integration',
  sources=globs('*_integration_test.py'),
  dependencies=[
    'src/python/pants/util:contextutil',
    'src/python/pants/testutil:int-test',
    'testprojects/src/python:plugins_directory',
  ],
  tags = {'integration'},
  timeout=90,
)
