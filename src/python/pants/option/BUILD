# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  dependencies=[
    '3rdparty/python:ansicolors',
    '3rdparty/python:dataclasses',
    '3rdparty/python:python-Levenshtein',
    '3rdparty/python:PyYAML',
    '3rdparty/python:setuptools',
    '3rdparty/python:toml',
    '3rdparty/python:typing-extensions',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:deprecated',
    'src/python/pants/base:hash_utils',
    'src/python/pants/engine:selectors',
    'src/python/pants/util:collections',
    'src/python/pants/util:eval',
    'src/python/pants/util:logging',
    'src/python/pants/util:memo',
    'src/python/pants/util:meta',
    'src/python/pants/util:objects',
    'src/python/pants/util:ordered_set',
    'src/python/pants/util:strutil',
  ],
  tags = {'partially_type_checked'},
)

python_tests(
  name="tests",
  sources=['*_test.py', '!*_integration_test.py'],
  dependencies=[
    ':option',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:hash_utils',
    'src/python/pants/base:deprecated',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:ordered_set',
    'src/python/pants/testutil/option',
    'src/python/pants/testutil:test_base',
  ],
  tags = {'partially_type_checked'},
)

python_tests(
  name='integration',
  sources=['*_integration_test.py'],
  dependencies=[
    'src/python/pants/testutil:int-test',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:logging',
    'testprojects/src/python:plugins_directory',
  ],
  tags = {'integration', 'partially_type_checked'},
  timeout=120,
)
